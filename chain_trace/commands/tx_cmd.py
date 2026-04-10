"""trace tx — detailed view of a single transaction."""
import sys
import click
import requests

from chain_trace.db.labels import get_label


def _label_fn(conn):
    def fn(address: str, chain: str) -> str | None:
        result = get_label(conn, address, chain)
        return result["name"] if result else None
    return fn


@click.command("tx")
@click.argument("tx_hash")
@click.option("--chain", type=click.Choice(["btc", "eth"]), default=None,
              help="Chain (auto-detected from hash format if omitted)")
@click.option("--usd", "show_usd", is_flag=True, help="Show USD value")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_context
def tx_cmd(ctx, tx_hash, chain, show_usd, as_json):
    """Show full transfer detail for a single transaction.

    Useful for inspecting multi-hop DEX swaps and complex contract calls.
    """
    conn = ctx.obj["db"]

    # Auto-detect chain: ETH hashes start with 0x and are 66 chars
    if chain is None:
        if tx_hash.startswith("0x") and len(tx_hash) == 66:
            chain = "eth"
        else:
            chain = "btc"

    api_key_row = conn.execute(
        "SELECT value FROM config WHERE key = 'etherscan_key'"
    ).fetchone()
    api_key = api_key_row["value"] if api_key_row else ""

    label_fn = _label_fn(conn)

    try:
        if chain == "eth":
            _show_eth_tx(conn, tx_hash, api_key, label_fn, show_usd, as_json)
        else:
            _show_btc_tx(conn, tx_hash, label_fn, show_usd, as_json)
    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    except requests.exceptions.HTTPError as e:
        click.echo(f"HTTP error: {e}", err=True)
        sys.exit(1)


def _show_eth_tx(conn, tx_hash, api_key, label_fn, show_usd, as_json):
    if not api_key:
        click.echo("Error: Etherscan API key not set. Run: trace config set etherscan_key <KEY>", err=True)
        sys.exit(1)

    from chain_trace.chains.ethereum import fetcher, parser, classifier
    from chain_trace.catalog.loader import get_dex_routers
    from chain_trace.output.rich_tables import print_single_tx

    # Fetch all token transfers for this specific tx
    # We use internal + token endpoints filtered by address=tx_hash not available directly,
    # so we fetch the tx via a broad search and filter by hash.
    # The cleanest way: use Etherscan's token transfer + internal tx APIs filtered to the tx block.
    # For simplicity: fetch a broad search and find matching tx.
    # Better approach: use Etherscan's `txlistinternal?txhash=` which IS supported.

    # Fetch internal txs for this specific tx hash
    import time
    import requests as req_lib

    def fetch_by_hash(action: str) -> list:
        time.sleep(0.25)
        params = {
            "module": "account",
            "action": action,
            "txhash": tx_hash,
            "apikey": api_key,
            "chainid": "1",
        }
        resp = req_lib.get("https://api.etherscan.io/v2/api", params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "0" and "No transactions" in data.get("message", ""):
            return []
        if data.get("status") == "0":
            return []
        return data.get("result", [])

    internal_raw = fetch_by_hash("txlistinternal")
    token_raw = fetch_by_hash("tokentx")

    # Parse
    token_transfers, _ = parser.parse_token_transfers(token_raw)
    internal_transfers = parser.parse_internal_txs(internal_raw, "")

    # Merge all transfers for this tx
    all_transfers = list(token_transfers.get(tx_hash.lower(), []))
    all_transfers += list(internal_transfers.get(tx_hash.lower(), []))

    # Build a synthetic meta from available data
    if token_raw:
        meta = {
            "block": int(token_raw[0].get("blockNumber", 0)),
            "timestamp": parser._ts(token_raw[0]),
            "from": token_raw[0].get("from", "").lower(),
            "to": token_raw[0].get("to", "").lower(),
            "value_wei": 0,
            "is_error": False,
            "method": "",
        }
    elif internal_raw:
        meta = {
            "block": int(internal_raw[0].get("blockNumber", 0)),
            "timestamp": parser._ts(internal_raw[0]),
            "from": internal_raw[0].get("from", "").lower(),
            "to": internal_raw[0].get("to", "").lower(),
            "value_wei": int(internal_raw[0].get("value", 0)),
            "is_error": False,
            "method": "",
        }
    else:
        click.echo(f"No transfer data found for tx {tx_hash}", err=True)
        sys.exit(1)

    dex_routers = get_dex_routers(conn)

    # Classify from perspective of the "from" address
    address = meta["from"]
    event = classifier.classify_eth_tx(address, tx_hash.lower(), meta, all_transfers, dex_routers)

    if event is None:
        click.echo("Transaction has no net impact on the from address.", err=True)
        sys.exit(0)

    # Enrich labels
    event.counterparty_label = label_fn(event.counterparty, "eth") if event.counterparty else None

    print_single_tx(event, label_fn, as_json=as_json)


def _show_btc_tx(conn, tx_hash, label_fn, show_usd, as_json):
    import requests as req_lib
    import time

    time.sleep(0.1)
    resp = req_lib.get(f"https://mempool.space/api/tx/{tx_hash}", timeout=20)
    resp.raise_for_status()
    tx = resp.json()

    from chain_trace.output.rich_tables import print_single_tx, console
    from chain_trace.models import TxEvent, TxType, Chain, TokenTransfer
    from decimal import Decimal
    from datetime import datetime

    block_time = tx.get("status", {}).get("block_time")
    ts = datetime.utcfromtimestamp(block_time) if block_time else datetime.utcnow()
    block = tx.get("status", {}).get("block_height", 0)

    # Build transfers for all significant inputs/outputs
    transfers = []
    for inp in tx.get("vin", []):
        po = inp.get("prevout", {})
        addr = po.get("scriptpubkey_address")
        val = po.get("value", 0)
        if addr and val:
            transfers.append(TokenTransfer(
                from_address=addr,
                to_address="(outputs)",
                asset_symbol="BTC",
                asset_address=None,
                amount=Decimal(val) / Decimal(10**8),
            ))

    for out in tx.get("vout", []):
        addr = out.get("scriptpubkey_address")
        val = out.get("value", 0)
        if addr and val:
            transfers.append(TokenTransfer(
                from_address="(inputs)",
                to_address=addr,
                asset_symbol="BTC",
                asset_address=None,
                amount=Decimal(val) / Decimal(10**8),
            ))

    total_in = sum(
        Decimal(inp.get("prevout", {}).get("value", 0)) / Decimal(10**8)
        for inp in tx.get("vin", [])
    )
    fee = Decimal(tx.get("fee", 0)) / Decimal(10**8)

    event = TxEvent(
        tx_hash=tx_hash,
        chain=Chain.BTC,
        block=block,
        timestamp=ts,
        kind=TxType.SEND,
        net_flows={"BTC (total in)": total_in, "BTC (fee)": -fee},
        raw_transfers=transfers,
    )

    print_single_tx(event, label_fn, as_json=as_json)
