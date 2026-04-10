"""ETH transaction classification logic."""
from collections import defaultdict
from decimal import Decimal
from chain_trace.models import TxEvent, TxType, Chain, TokenTransfer
from chain_trace.chains.ethereum.parser import WETH_CONTRACT

# LP token symbol patterns that indicate a liquidity event
_LP_SYMBOLS = {"UNI-V2", "SLP", "CAKE-LP", "BPT", "G-UNI", "ELIXIR"}
_LP_SUFFIXES = ("-LP", "-POOL", "-V2", "-V3")


def _is_lp_token(symbol: str) -> bool:
    if symbol in _LP_SYMBOLS:
        return True
    return any(symbol.endswith(s) for s in _LP_SUFFIXES)


def classify_eth_tx(
    address: str,
    tx_hash: str,
    meta: dict,
    transfers: list[TokenTransfer],
    dex_routers: dict[str, str],
) -> TxEvent | None:
    """Classify a single Ethereum transaction from the perspective of `address`.

    Returns a TxEvent, or None if the tx has no meaningful impact on address
    (e.g. a failed tx or a zero-value contract call with no token movement).
    """
    addr = address.lower()
    weth = WETH_CONTRACT.lower()

    # Compute net flows for the queried address
    net: dict[str, Decimal] = defaultdict(Decimal)
    for t in transfers:
        if t.to_address == addr:
            net[t.asset_symbol] += t.amount
        if t.from_address == addr:
            net[t.asset_symbol] -= t.amount

    # Remove zero-net entries (e.g. loopback transfers)
    net = {k: v for k, v in net.items() if v != Decimal(0)}

    # No impact on this address at all
    if not net and meta.get("from") != addr and meta.get("to") != addr:
        return None

    inflow_assets = {k for k, v in net.items() if v > 0}
    outflow_assets = {k for k, v in net.items() if v < 0}

    # Gather all counterparty addresses
    all_counterparties = set()
    for t in transfers:
        if t.from_address != addr:
            all_counterparties.add(t.from_address)
        if t.to_address != addr:
            all_counterparties.add(t.to_address)
    if meta.get("to") and meta["to"] != addr:
        all_counterparties.add(meta["to"])

    # ── WRAP (ETH → WETH, direct to WETH contract) ────────────────────────
    if (
        inflow_assets == {"WETH"}
        and outflow_assets == {"ETH"}
        and meta.get("to") == weth
    ):
        return TxEvent(
            tx_hash=tx_hash,
            chain=Chain.ETH,
            block=meta["block"],
            timestamp=meta["timestamp"],
            kind=TxType.WRAP,
            net_flows=dict(net),
            raw_transfers=transfers,
        )

    # ── UNWRAP (WETH → ETH, direct to WETH contract) ──────────────────────
    if (
        inflow_assets == {"ETH"}
        and outflow_assets == {"WETH"}
        and meta.get("to") == weth
    ):
        return TxEvent(
            tx_hash=tx_hash,
            chain=Chain.ETH,
            block=meta["block"],
            timestamp=meta["timestamp"],
            kind=TxType.UNWRAP,
            net_flows=dict(net),
            raw_transfers=transfers,
        )

    # ── LIQUIDITY (LP token involved) ─────────────────────────────────────
    all_symbols = {t.asset_symbol for t in transfers}
    if any(_is_lp_token(s) for s in all_symbols):
        lp_action = "remove" if inflow_assets and not outflow_assets else "add"
        if inflow_assets and outflow_assets:
            # Receiving LP tokens → adding liquidity
            lp_tokens_in = {a for a in inflow_assets if _is_lp_token(a)}
            lp_action = "add" if lp_tokens_in else "remove"
        dex_name = next(
            (dex_routers[a] for a in all_counterparties if a in dex_routers), None
        )
        return TxEvent(
            tx_hash=tx_hash,
            chain=Chain.ETH,
            block=meta["block"],
            timestamp=meta["timestamp"],
            kind=TxType.LIQUIDITY,
            net_flows=dict(net),
            lp_action=lp_action,
            pool_label=dex_name,
            raw_transfers=transfers,
        )

    # ── SWAP (different inflow and outflow assets) ─────────────────────────
    dex_name = next(
        (dex_routers[a] for a in all_counterparties if a in dex_routers), None
    )
    if inflow_assets and outflow_assets:
        # Find hops: look at intermediate assets in all transfers (not net)
        # Simple heuristic: all unique assets involved in this tx
        all_assets_in_tx = {t.asset_symbol for t in transfers}
        intermediate = all_assets_in_tx - inflow_assets - outflow_assets
        hops_list = (
            list(outflow_assets) + list(intermediate) + list(inflow_assets)
            if intermediate
            else None
        )
        return TxEvent(
            tx_hash=tx_hash,
            chain=Chain.ETH,
            block=meta["block"],
            timestamp=meta["timestamp"],
            kind=TxType.SWAP,
            net_flows=dict(net),
            dex_name=dex_name,
            hops=hops_list,
            raw_transfers=transfers,
        )

    # ── RECEIVE (only inflows) ─────────────────────────────────────────────
    if inflow_assets and not outflow_assets:
        # Find the main sender
        counterparty = None
        for t in transfers:
            if t.to_address == addr:
                counterparty = t.from_address
                break
        if counterparty is None and meta.get("from"):
            counterparty = meta["from"]
        return TxEvent(
            tx_hash=tx_hash,
            chain=Chain.ETH,
            block=meta["block"],
            timestamp=meta["timestamp"],
            kind=TxType.RECEIVE,
            net_flows=dict(net),
            counterparty=counterparty,
            raw_transfers=transfers,
        )

    # ── TRANSFER (only outflows, or a zero-value contract call) ───────────
    if outflow_assets and not inflow_assets:
        counterparty = None
        for t in transfers:
            if t.from_address == addr and t.to_address != addr:
                counterparty = t.to_address
                break
        if counterparty is None and meta.get("to"):
            counterparty = meta["to"]
        return TxEvent(
            tx_hash=tx_hash,
            chain=Chain.ETH,
            block=meta["block"],
            timestamp=meta["timestamp"],
            kind=TxType.TRANSFER,
            net_flows=dict(net),
            counterparty=counterparty,
            raw_transfers=transfers,
        )

    # ── CONTRACT fallback ──────────────────────────────────────────────────
    # Zero net or no transfers but tx exists (contract call, failed, etc.)
    if not net:
        return None  # Skip zero-impact txs

    return TxEvent(
        tx_hash=tx_hash,
        chain=Chain.ETH,
        block=meta["block"],
        timestamp=meta["timestamp"],
        kind=TxType.CONTRACT,
        net_flows=dict(net),
        raw_transfers=transfers,
    )
