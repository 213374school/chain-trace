"""Label management commands."""
import json
import click
from rich.console import Console
from rich.table import Table

from chain_trace.db.labels import get_label, set_label, remove_label, list_labels

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
