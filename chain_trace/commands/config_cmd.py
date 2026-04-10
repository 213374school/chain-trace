import json
import click
from rich.console import Console
from rich.table import Table

console = Console()

_SENSITIVE = {"etherscan_key"}


@click.group("config")
def config_cmd():
    """Manage configuration (API keys, thresholds)."""


@config_cmd.command("set")
@click.argument("key")
@click.argument("value")
@click.pass_context
def config_set(ctx, key: str, value: str):
    """Set a configuration value."""
    conn = ctx.obj["db"]
    conn.execute(
        "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, value)
    )
    conn.commit()
    display = "***" if key in _SENSITIVE and value else value
    console.print(f"[green]✓[/green] {key} = {display}")


@config_cmd.command("get")
@click.argument("key")
@click.pass_context
def config_get(ctx, key: str):
    """Get a single configuration value."""
    conn = ctx.obj["db"]
    row = conn.execute("SELECT value FROM config WHERE key = ?", (key,)).fetchone()
    if not row:
        console.print(f"[red]Key '{key}' not found[/red]")
        raise SystemExit(1)
    value = "***" if key in _SENSITIVE else row["value"]
    console.print(f"{key} = {value}")


@config_cmd.command("list")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_context
def config_list(ctx, as_json: bool):
    """List all configuration values."""
    conn = ctx.obj["db"]
    rows = conn.execute("SELECT key, value FROM config ORDER BY key").fetchall()

    data = {
        r["key"]: ("***" if r["key"] in _SENSITIVE and r["value"] else r["value"])
        for r in rows
    }

    if as_json:
        click.echo(json.dumps(data, indent=2))
        return

    table = Table(title="Configuration", show_header=True, header_style="bold cyan")
    table.add_column("Key", style="cyan", no_wrap=True)
    table.add_column("Value")
    for k, v in data.items():
        table.add_row(k, v)
    console.print(table)
