"""Investigation session commands."""
import json
import sys
import click
from datetime import datetime
from rich.console import Console
from rich.table import Table

from chain_trace.db import sessions as session_db
from chain_trace.db.labels import get_label

console = Console()


def _require_session(conn, name: str) -> dict:
    session = session_db.get_session(conn, name)
    if not session:
        click.echo(
            f"Session '{name}' not found. Create it with: trace session new {name}",
            err=True,
        )
        sys.exit(1)
    return session


@click.group("session")
def session_cmd():
    """Manage investigation sessions."""


@session_cmd.command("new")
@click.argument("name")
@click.option("--notes", default=None)
@click.pass_context
def session_new(ctx, name, notes):
    """Create a new investigation session."""
    conn = ctx.obj["db"]
    if session_db.get_session(conn, name):
        console.print(f"[yellow]Session '{name}' already exists.[/yellow]")
        return
    session_db.create_session(conn, name, notes)
    console.print(f"[green]✓[/green] Created session '[bold]{name}[/bold]'")


@session_cmd.command("list")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def session_list(ctx, as_json):
    """List all sessions."""
    conn = ctx.obj["db"]
    sessions = session_db.list_sessions(conn)

    if as_json:
        # Convert timestamps
        for s in sessions:
            s["created_at"] = datetime.utcfromtimestamp(s["created_at"]).isoformat()
        click.echo(json.dumps(sessions, indent=2))
        return

    if not sessions:
        console.print("[yellow]No sessions. Create one with: trace session new <name>[/yellow]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Name", style="cyan")
    table.add_column("Created")
    table.add_column("Notes", style="bright_black")

    for s in sessions:
        created = datetime.utcfromtimestamp(s["created_at"]).strftime("%Y-%m-%d")
        table.add_row(s["name"], created, s.get("notes") or "—")

    console.print(table)


@session_cmd.command("add")
@click.argument("session_name")
@click.argument("address")
@click.option("--chain", type=click.Choice(["btc", "eth"]), required=True)
@click.pass_context
def session_add(ctx, session_name, address, chain):
    """Add an address to a session."""
    conn = ctx.obj["db"]
    session = _require_session(conn, session_name)
    session_db.add_address(conn, session["id"], address, chain)
    label_row = get_label(conn, address, chain)
    label = f" ({label_row['name']})" if label_row else ""
    console.print(
        f"[green]✓[/green] Added [cyan]{address}{label}[/cyan] ({chain}) "
        f"to session '[bold]{session_name}[/bold]'"
    )


@session_cmd.command("remove-address")
@click.argument("session_name")
@click.argument("address")
@click.option("--chain", type=click.Choice(["btc", "eth"]), required=True)
@click.pass_context
def session_remove_address(ctx, session_name, address, chain):
    """Remove an address from a session."""
    conn = ctx.obj["db"]
    session = _require_session(conn, session_name)
    removed = session_db.remove_address(conn, session["id"], address, chain)
    if removed:
        console.print(f"[green]✓[/green] Removed {address} from session '{session_name}'")
    else:
        console.print(f"[yellow]Address not found in session '{session_name}'[/yellow]")


@session_cmd.command("dead-end")
@click.argument("session_name")
@click.argument("address")
@click.option("--chain", type=click.Choice(["btc", "eth"]), required=True)
@click.option("--reason", default=None, help="Reason for marking as dead end")
@click.pass_context
def session_dead_end(ctx, session_name, address, chain, reason):
    """Mark an address as a dead end (e.g. CEX — stops follow suggestions)."""
    conn = ctx.obj["db"]
    session = _require_session(conn, session_name)
    # Add it first if not already there
    session_db.add_address(conn, session["id"], address, chain)
    session_db.mark_dead_end(conn, session["id"], address, chain, reason)
    console.print(
        f"[red]✗[/red] Marked [cyan]{address}[/cyan] ({chain}) as dead end"
        + (f": {reason}" if reason else "")
    )


@session_cmd.command("show")
@click.argument("session_name")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def session_show(ctx, session_name, as_json):
    """Show addresses in a session."""
    conn = ctx.obj["db"]
    session = _require_session(conn, session_name)
    addresses = session_db.get_session_addresses(conn, session["id"])

    if as_json:
        click.echo(json.dumps(
            {"session": session_name, "addresses": addresses}, indent=2
        ))
        return

    table = Table(
        title=f"Session: {session_name}",
        show_header=True, header_style="bold",
    )
    table.add_column("Address", style="cyan", no_wrap=True)
    table.add_column("Chain")
    table.add_column("Label")
    table.add_column("Status")
    table.add_column("Dead-end reason", style="bright_black")

    for addr_row in addresses:
        label_row = get_label(conn, addr_row["address"], addr_row["chain"])
        label = label_row["name"] if label_row else "—"
        status = "[red]dead end[/red]" if addr_row["is_dead_end"] else "[green]active[/green]"
        table.add_row(
            addr_row["address"],
            addr_row["chain"],
            label,
            status,
            addr_row.get("dead_end_reason") or "—",
        )

    console.print(table)


@session_cmd.command("timeline")
@click.argument("session_name")
@click.option("--from", "from_date", default=None)
@click.option("--to", "to_date", default=None)
@click.option("--usd", "show_usd", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def session_timeline(ctx, session_name, from_date, to_date, show_usd, as_json):
    """Unified chronological view across all active session addresses."""
    conn = ctx.obj["db"]
    session = _require_session(conn, session_name)

    api_key_row = conn.execute(
        "SELECT value FROM config WHERE key = 'etherscan_key'"
    ).fetchone()
    api_key = api_key_row["value"] if api_key_row else ""

    addresses = session_db.get_session_addresses(conn, session["id"], active_only=True)
    if not addresses:
        console.print("[yellow]No active addresses in this session.[/yellow]")
        return

    from dateutil import parser as dateparser
    from_dt = dateparser.parse(from_date) if from_date else None
    to_dt = dateparser.parse(to_date) if to_date else None

    from chain_trace.models import Chain
    from chain_trace.commands.trace_cmd import (
        _trace_eth_events, _trace_btc_events,
    )
    from chain_trace.output.rich_tables import print_events
    from chain_trace.db.labels import get_label as _get_label

    def label_fn(addr, chain_val):
        row = _get_label(conn, addr, chain_val)
        return row["name"] if row else None

    # Set of active addresses for dedup
    active_set = {(r["address"], r["chain"]) for r in addresses}

    all_events = []
    seen_hashes = set()

    for addr_row in addresses:
        addr = addr_row["address"]
        chain_val = addr_row["chain"]
        chain = Chain(chain_val)

        dust_row = conn.execute(
            f"SELECT value FROM config WHERE key = 'dust_threshold_{chain_val}'"
        ).fetchone()
        dust = float(dust_row["value"]) if dust_row else 0.0001

        try:
            if chain == Chain.ETH:
                events = _trace_eth_events(
                    conn, addr, api_key, from_dt, to_dt, 500, dust, False, False, None
                )
            else:
                from_ts = int(from_dt.timestamp()) if from_dt else None
                to_ts = int(to_dt.timestamp()) if to_dt else None
                events = _trace_btc_events(conn, addr, 500, from_ts, to_ts, dust)
        except Exception as e:
            console.print(f"[yellow]Warning: could not fetch {addr}: {e}[/yellow]")
            continue

        for event in events:
            if event.tx_hash in seen_hashes:
                continue
            # Check if counterparty is also in our session → mark internal
            if event.counterparty and (event.counterparty, chain_val) in active_set:
                event.counterparty_label = label_fn(event.counterparty, chain_val)
                # Mark as internal — will show once
            seen_hashes.add(event.tx_hash)
            all_events.append(event)

    # Sort chronologically
    all_events.sort(key=lambda e: e.timestamp)

    if as_json:
        from chain_trace.output.json_output import events_to_json
        print(events_to_json(all_events, session_name, Chain.ETH, from_date, to_date))
        return

    console.print(f"\n  [bold]Session timeline:[/bold] {session_name}")
    console.print(f"  {len(all_events)} events across {len(addresses)} addresses\n")
    print_events(all_events, session_name, Chain.ETH, label_fn, from_date=from_date, to_date=to_date)


@session_cmd.command("export")
@click.argument("session_name")
@click.option("--format", "fmt", type=click.Choice(["json", "csv"]), default="json")
@click.option("--output", "output_file", default=None, help="Output file (default: stdout)")
@click.pass_context
def session_export(ctx, session_name, fmt, output_file):
    """Export session data to JSON or CSV."""
    conn = ctx.obj["db"]
    session = _require_session(conn, session_name)
    addresses = session_db.get_session_addresses(conn, session["id"])

    data = {
        "session": session_name,
        "exported_at": datetime.utcnow().isoformat(),
        "addresses": [
            {
                "address": r["address"],
                "chain": r["chain"],
                "is_dead_end": bool(r["is_dead_end"]),
                "dead_end_reason": r.get("dead_end_reason"),
                "added_at": datetime.utcfromtimestamp(r["added_at"]).isoformat(),
            }
            for r in addresses
        ],
    }

    if fmt == "json":
        output = json.dumps(data, indent=2)
    else:
        import io
        import csv as csv_lib
        buf = io.StringIO()
        writer = csv_lib.DictWriter(
            buf,
            fieldnames=["address", "chain", "is_dead_end", "dead_end_reason", "added_at"],
        )
        writer.writeheader()
        writer.writerows(data["addresses"])
        output = buf.getvalue()

    if output_file:
        with open(output_file, "w") as f:
            f.write(output)
        console.print(f"[green]✓[/green] Exported to {output_file}")
    else:
        click.echo(output)
