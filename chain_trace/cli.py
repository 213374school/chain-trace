import click
from chain_trace.db.connection import get_connection, DEFAULT_DB
from chain_trace.catalog.loader import load_catalog
from chain_trace.commands.config_cmd import config_cmd
from chain_trace.commands.trace_cmd import trace_cmd
from chain_trace.commands.tx_cmd import tx_cmd
from chain_trace.commands.label_cmd import label_cmd
from chain_trace.commands.session_cmd import session_cmd


@click.group()
@click.option(
    "--db",
    "db_path",
    default=None,
    metavar="PATH",
    help=f"Database path (default: {DEFAULT_DB})",
)
@click.pass_context
def cli(ctx, db_path):
    """Forensic blockchain transaction tracer.

    Supports Bitcoin (BTC) and Ethereum (ETH + ERC-20).
    Chain is auto-detected from address format.
    """
    ctx.ensure_object(dict)
    conn = get_connection(db_path)
    ctx.obj["db"] = conn
    load_catalog(conn)


cli.add_command(config_cmd, "config")
cli.add_command(trace_cmd, "trace")
cli.add_command(tx_cmd, "tx")
cli.add_command(label_cmd, "label")
cli.add_command(session_cmd, "session")


if __name__ == "__main__":
    cli()
