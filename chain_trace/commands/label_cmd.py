"""Label management commands."""
import json
import click
from rich.console import Console
from rich.table import Table

from chain_trace.db.labels import get_label, set_label, remove_label, list_labels, resolve_label

console = Console()


@click.group("label")
def label_cmd():
    """Manage address labels."""


@label_cmd.command("add")
@click.argument("address")
@click.argument("name")
@click.option("--chain", type=click.Choice(["btc", "eth", "any"]), default="any",
              show_default=True, help="Chain scope for this label")
@click.option("--category", default=None, help="Category (exchange, dex, bridge, etc.)")
@click.option("--notes", default=None, help="Optional notes")
@click.pass_context
def label_add(ctx, address, name, chain, category, notes):
    """Add or update a label for an address."""
    conn = ctx.obj["db"]
    set_label(conn, address, name, chain=chain, category=category, notes=notes)
    console.print(f"[green]✓[/green] Labelled [cyan]{address}[/cyan] as '{name}' ({chain})")


@label_cmd.command("remove")
@click.argument("address")
@click.option("--chain", type=click.Choice(["btc", "eth", "any"]), default="any")
@click.pass_context
def label_remove(ctx, address, chain):
    """Remove a user-defined label."""
    conn = ctx.obj["db"]
    removed = remove_label(conn, address, chain)
    if removed:
        console.print(f"[green]✓[/green] Removed label for [cyan]{address}[/cyan] ({chain})")
    else:
        console.print(
            f"[yellow]No user label found for {address} ({chain})[/yellow]\n"
            "Note: catalog labels cannot be removed."
        )


@label_cmd.command("list")
@click.option("--chain", type=click.Choice(["btc", "eth", "any"]), default=None)
@click.option("--category", default=None)
@click.option("--source", type=click.Choice(["user", "catalog"]), default=None)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def label_list(ctx, chain, category, source, as_json):
    """List all labels."""
    conn = ctx.obj["db"]
    labels = list_labels(conn, chain=chain, category=category, source=source)

    if as_json:
        click.echo(json.dumps(labels, indent=2))
        return

    if not labels:
        console.print("[yellow]No labels found.[/yellow]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Address", style="cyan", no_wrap=True)
    table.add_column("Chain")
    table.add_column("Name")
    table.add_column("Category", style="bright_black")
    table.add_column("Source", style="bright_black")

    for lb in labels:
        table.add_row(
            lb["address"],
            lb["chain"],
            lb["name"],
            lb.get("category") or "—",
            lb["source"],
        )

    console.print(f"  {len(labels)} labels")
    console.print(table)


@label_cmd.command("lookup")
@click.argument("address")
@click.option("--chain", type=click.Choice(["eth"]), default="eth", show_default=True,
              help="Chain to query (only 'eth' is supported by Chainbase address labels)")
@click.option("--save", is_flag=True,
              help="Persist the result to the local label database")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_context
def label_lookup(ctx, address, chain, save, as_json):
    """Look up an address label via Chainbase API.

    Checks the local database first; if no label is found it queries Chainbase.
    Use --save to store the result locally for future offline lookups.

    Requires a Chainbase API key:
      trace config set chainbase_key YOUR_KEY
    """
    conn = ctx.obj["db"]

    # Check key early to give a helpful error before hitting the network
    row = conn.execute(
        "SELECT value FROM config WHERE key = 'chainbase_key'"
    ).fetchone()
    api_key = row["value"] if row else ""
    if not api_key:
        console.print(
            "[red]Chainbase API key not configured.[/red]\n"
            "Run:  trace config set chainbase_key YOUR_KEY\n"
            "Get a free key at https://chainbase.com"
        )
        raise SystemExit(1)

    # Local check first (avoids a network call when already labelled)
    local = get_label(conn, address, chain)
    if local:
        result = local
        source_note = local.get("source", "local")
    else:
        from chain_trace.labels.chainbase import fetch_label
        fetched = fetch_label(conn, address, chain, api_key)
        result = fetched
        source_note = "chainbase"

        if fetched and save:
            set_label(
                conn,
                address,
                fetched["name"],
                chain=chain,
                category=fetched.get("category"),
                source="chainbase",
            )

    if as_json:
        payload = {
            "address": address,
            "chain": chain,
            "label": result,
            "source": source_note if result else None,
        }
        click.echo(json.dumps(payload, indent=2))
        return

    if not result:
        console.print(
            f"[yellow]No label found for [cyan]{address}[/cyan] on {chain}[/yellow]"
        )
        return

    console.print(f"[cyan]{address}[/cyan]  ({chain})")
    console.print(f"  Name:     [bold]{result['name']}[/bold]")
    if result.get("category"):
        console.print(f"  Category: {result['category']}")
    console.print(f"  Source:   {source_note}")
    if save and source_note == "chainbase" and not local:
        console.print("  [green]✓ Saved to local database[/green]")
