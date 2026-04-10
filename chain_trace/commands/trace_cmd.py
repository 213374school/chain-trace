"""Main trace command — query an address on BTC or ETH."""
import sys
import click
import requests
from datetime import datetime
from dateutil import parser as dateparser

from chain_trace.models import Chain
from chain_trace.db.labels import get_label
from chain_trace.catalog.loader import get_dex_routers


def _detect_chain(address: str) -> Chain | None:
    """Auto-detect chain from address format."""
    if address.startswith("0x") and len(address) == 42:
        return Chain.ETH
    if address.startswith(("1", "3", "bc1", "BC1")):
        return Chain.BTC
    return None


def _parse_date(s: str) -> datetime:
    try:
        return dateparser.parse(s)
    except Exception:
        raise click.BadParameter(f"Cannot parse date: {s!r}. Use ISO format e.g. 2020-01-15")


def _label_fn(conn):
    """Returns a closure that looks up labels for display."""
    def fn(address: str, chain: str) -> str | None:
        result = get_label(conn, address, chain)
        return result["name"] if result else None
    return fn


@click.command("trace")
@click.argument("address")
@click.option("--chain", "chain_opt", type=click.Choice(["btc", "eth"]), default=None,
              help="Override auto-detected chain")
@click.option("--from", "from_date", default=None, metavar="DATE",
              help="Start date (ISO format, e.g. 2020-01-15)")
@click.option("--to", "to_date", default=None, metavar="DATE",
              help="End date (ISO format)")
@click.option("--limit", default=100, show_default=True, help="Max transactions")
@click.option("--usd", "show_usd", is_flag=True, help="Show USD value at tx date")
@click.option("--min-amount", "min_amount", default=None, type=float,
              help="Override dust threshold")
@click.option("--include-failed", is_flag=True, help="Include failed transactions")
@click.option("--include-approvals", is_flag=True, help="Include ERC-20 approve() calls")
@click.option("--session", "session_name", default=None,
              help="Log this address to a named session")
@click.option("--token", "token_contract", default=None, metavar="CONTRACT",
              help="Filter to a specific ERC-20 contract address (ETH only)")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_context
def trace_cmd(
    ctx,
    address,
    chain_opt,
    from_date,
    to_date,
    limit,
    show_usd,
    min_amount,
    include_failed,
    include_approvals,
    session_name,
    token_contract,
    as_json,
):
    """Trace transfers to/from an address.

    ADDRESS can be a Bitcoin or Ethereum address — chain is auto-detected.
    """
    conn = ctx.obj["db"]

    # Resolve chain
    if chain_opt:
        chain = Chain(chain_opt)
    else:
        chain = _detect_chain(address)
        if chain is None:
            raise click.UsageError(
                f"Cannot auto-detect chain for address: {address!r}\n"
                "Specify --chain btc or --chain eth"
            )

    # Parse dates
    from_dt = _parse_date(from_date) if from_date else None
    to_dt = _parse_date(to_date) if to_date else None

    # Get config
    api_key_row = conn.execute(
        "SELECT value FROM config WHERE key = 'etherscan_key'"
    ).fetchone()
    etherscan_key = api_key_row["value"] if api_key_row else ""
    dust_row = conn.execute(
        f"SELECT value FROM config WHERE key = 'dust_threshold_{chain.value}'"
    ).fetchone()
    dust = min_amount if min_amount is not None else float(dust_row["value"] if dust_row else 0.0001)

    label_fn = _label_fn(conn)

    try:
        if chain == Chain.ETH:
            _trace_eth(
                conn, address, etherscan_key, from_dt, to_dt, limit, dust,
                include_failed, include_approvals, show_usd, token_contract,
                as_json, label_fn, from_date, to_date,
            )
        else:
            _trace_btc(
                conn, address, from_dt, to_dt, limit, dust, show_usd,
                as_json, label_fn, from_date, to_date,
            )
    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    except requests.exceptions.HTTPError as e:
        click.echo(f"HTTP error: {e}", err=True)
        sys.exit(1)

    # Log to session if requested
    if session_name:
        from chain_trace.db.sessions import get_session, add_address
        session = get_session(conn, session_name)
        if session:
            add_address(conn, session["id"], address, chain.value)
        else:
            click.echo(
                f"[warning] Session '{session_name}' not found — "
                "create it first with: trace session new",
                err=True,
            )


def _trace_eth_events(
    conn, address, api_key, from_dt, to_dt, limit, dust,
    include_failed, include_approvals, token_contract,
) -> list:
    """Reusable: fetch + classify ETH events, return list of TxEvent."""
    from chain_trace.chains.ethereum import fetcher, parser, classifier

    start_block = 0
    end_block = 99999999
    if from_dt:
        start_block = fetcher.get_block_by_timestamp(
            conn, int(from_dt.timestamp()), api_key, closest="after"
        )
    if to_dt:
        end_block = fetcher.get_block_by_timestamp(
            conn, int(to_dt.timestamp()), api_key, closest="before"
        )

    normal_txs = fetcher.get_normal_txs(
        conn, address, api_key, start_block, end_block, offset=min(limit * 2, 2000)
    )
    token_txs = fetcher.get_token_transfers(
        conn, address, api_key, start_block, end_block,
        offset=min(limit * 2, 2000),
        contract_address=token_contract,
    )
    internal_txs = fetcher.get_internal_txs(
        conn, address, api_key, start_block, end_block, offset=min(limit * 2, 2000)
    )

    normal_meta = parser.parse_normal_txs(normal_txs)
    token_transfers, token_meta = parser.parse_token_transfers(token_txs)
    internal_transfers = parser.parse_internal_txs(internal_txs)

    groups = parser.build_tx_groups(
        address, normal_meta, token_transfers, token_meta,
        internal_transfers, include_failed, dust,
    )

    dex_routers = get_dex_routers(conn)
    events = []
    for tx_hash, group in groups.items():
        event = classifier.classify_eth_tx(
            address, tx_hash, group["meta"], group["transfers"], dex_routers
        )
        if event is not None:
            events.append(event)

    events.sort(key=lambda e: e.timestamp, reverse=True)
    return events[:limit]


def _trace_btc_events(conn, address, limit, from_ts, to_ts, dust) -> list:
    """Reusable: fetch + parse BTC events, return list of TxEvent."""
    from chain_trace.chains.bitcoin import fetcher as btc_fetcher
    return btc_fetcher.get_tx_events(conn, address, limit, from_ts, to_ts, dust)


def _trace_eth(
    conn, address, api_key, from_dt, to_dt, limit, dust,
    include_failed, include_approvals, show_usd, token_contract,
    as_json, label_fn, from_date_str, to_date_str,
):
    if not api_key:
        click.echo(
            "Error: Etherscan API key not set.\n"
            "Run: trace config set etherscan_key <YOUR_KEY>",
            err=True,
        )
        sys.exit(1)

    from chain_trace.output.rich_tables import print_events, console
    from chain_trace.models import Chain

    if not as_json:
        console.print(f"  Fetching transactions for [cyan]{address}[/cyan]…")

    events = _trace_eth_events(
        conn, address, api_key, from_dt, to_dt, limit, dust,
        include_failed, include_approvals, token_contract,
    )

    # Enrich counterparty labels
    for event in events:
        if event.counterparty:
            event.counterparty_label = label_fn(event.counterparty, "eth")

    if show_usd:
        _enrich_usd_eth(conn, events)

    print_events(
        events, address, Chain.ETH, label_fn,
        as_json=as_json, from_date=from_date_str, to_date=to_date_str,
    )


def _trace_btc(
    conn, address, from_dt, to_dt, limit, dust, show_usd,
    as_json, label_fn, from_date_str, to_date_str,
):
    from chain_trace.output.rich_tables import print_events, console
    from chain_trace.models import Chain

    if not as_json:
        console.print(f"  Fetching transactions for [cyan]{address}[/cyan]…")

    from_ts = int(from_dt.timestamp()) if from_dt else None
    to_ts = int(to_dt.timestamp()) if to_dt else None

    events = _trace_btc_events(conn, address, limit, from_ts, to_ts, dust)

    # Enrich counterparty labels
    for event in events:
        if event.counterparty:
            event.counterparty_label = label_fn(event.counterparty, "btc")

    if show_usd:
        _enrich_usd_btc(conn, events)

    print_events(
        events, address, Chain.BTC, label_fn,
        as_json=as_json, from_date=from_date_str, to_date=to_date_str,
    )


def _enrich_usd_eth(conn, events):
    from chain_trace.prices.coingecko import get_historical_price
    from decimal import Decimal

    # Asset → CoinGecko coin ID mapping
    _coin_ids = {
        "ETH": "ethereum", "WETH": "ethereum", "WBTC": "wrapped-bitcoin",
        "USDC": "usd-coin", "USDT": "tether", "DAI": "dai",
        "LINK": "chainlink", "UNI": "uniswap", "AAVE": "aave",
    }

    for event in events:
        total_usd = Decimal(0)
        date_str = event.timestamp.strftime("%Y-%m-%d")
        for asset, amount in event.net_flows.items():
            coin_id = _coin_ids.get(asset)
            if coin_id:
                price = get_historical_price(conn, coin_id, date_str)
                if price:
                    total_usd += abs(amount) * Decimal(str(price))
        if total_usd > 0:
            event.usd_total = total_usd


def _enrich_usd_btc(conn, events):
    from chain_trace.prices.coingecko import get_historical_price
    from decimal import Decimal

    for event in events:
        date_str = event.timestamp.strftime("%Y-%m-%d")
        price = get_historical_price(conn, "bitcoin", date_str)
        if price:
            total = sum(abs(v) for v in event.net_flows.values())
            event.usd_total = total * Decimal(str(price))
