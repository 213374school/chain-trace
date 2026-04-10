"""Parse raw Etherscan API responses into unified tx groups."""
from collections import defaultdict
from decimal import Decimal
from datetime import datetime
from chain_trace.models import TokenTransfer

WETH_CONTRACT = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"


def _ts(raw: dict) -> datetime:
    try:
        return datetime.utcfromtimestamp(int(raw["timeStamp"]))
    except (KeyError, ValueError):
        return datetime.utcnow()


def parse_normal_txs(txlist: list[dict]) -> dict[str, dict]:
    """Raw txlist → {tx_hash: tx_meta_dict}"""
    result = {}
    for tx in txlist:
        h = tx.get("hash", "").lower()
        if not h:
            continue
        result[h] = {
            "block": int(tx.get("blockNumber", 0)),
            "timestamp": _ts(tx),
            "from": tx.get("from", "").lower(),
            "to": (tx.get("to") or "").lower(),
            "value_wei": int(tx.get("value", "0")),
            "is_error": tx.get("isError", "0") == "1",
            "method": tx.get("functionName", ""),
        }
    return result


def parse_token_transfers(tokentx: list[dict]) -> dict[str, list]:
    """Raw tokentx → {tx_hash: [TokenTransfer, ...]}
    Also returns per-hash metadata (block/timestamp) for txs not in normal list.
    """
    transfers: dict[str, list] = defaultdict(list)
    meta: dict[str, dict] = {}

    for tx in tokentx:
        h = tx.get("hash", "").lower()
        if not h:
            continue
        decimals = int(tx.get("tokenDecimal") or "18")
        try:
            amount = Decimal(tx.get("value", "0")) / Decimal(10**decimals)
        except Exception:
            amount = Decimal(0)

        transfers[h].append(
            TokenTransfer(
                from_address=tx.get("from", "").lower(),
                to_address=tx.get("to", "").lower(),
                asset_symbol=tx.get("tokenSymbol", "?"),
                asset_address=tx.get("contractAddress", "").lower(),
                amount=amount,
            )
        )
        if h not in meta:
            meta[h] = {
                "block": int(tx.get("blockNumber", 0)),
                "timestamp": _ts(tx),
                "from": tx.get("from", "").lower(),
                "to": tx.get("to", "").lower(),
                "value_wei": 0,
                "is_error": False,
                "method": "",
            }

    return dict(transfers), meta


def parse_internal_txs(internal: list[dict]) -> dict[str, list]:
    """Raw internal txs → {tx_hash: [TokenTransfer, ...]} for ETH internal transfers."""
    result: dict[str, list] = defaultdict(list)
    for tx in internal:
        if tx.get("isError", "0") == "1":
            continue
        value_wei = int(tx.get("value", "0"))
        if value_wei == 0:
            continue
        h = tx.get("hash", "").lower()
        if not h:
            continue
        amount = Decimal(value_wei) / Decimal(10**18)
        result[h].append(
            TokenTransfer(
                from_address=tx.get("from", "").lower(),
                to_address=tx.get("to", "").lower(),
                asset_symbol="ETH",
                asset_address=None,
                amount=amount,
            )
        )
    return dict(result)


def build_tx_groups(
    address: str,
    normal_meta: dict[str, dict],
    token_transfers: dict[str, list],
    token_meta: dict[str, dict],
    internal_transfers: dict[str, list],
    include_failed: bool = False,
    dust_eth: float = 0.0001,
) -> dict[str, dict]:
    """Merge all sources into: {tx_hash: {meta, transfers: [TokenTransfer]}}"""
    addr = address.lower()
    all_hashes = (
        set(normal_meta.keys()) | set(token_transfers.keys()) | set(internal_transfers.keys())
    )

    groups: dict[str, dict] = {}
    for h in all_hashes:
        meta = normal_meta.get(h) or token_meta.get(h)
        if meta is None:
            continue
        if meta["is_error"] and not include_failed:
            continue

        transfers: list[TokenTransfer] = []

        # Native ETH from normal tx
        if meta["value_wei"] > 0:
            eth_amount = Decimal(meta["value_wei"]) / Decimal(10**18)
            if float(eth_amount) >= dust_eth:
                transfers.append(
                    TokenTransfer(
                        from_address=meta["from"],
                        to_address=meta["to"],
                        asset_symbol="ETH",
                        asset_address=None,
                        amount=eth_amount,
                    )
                )

        # Internal ETH (received from contracts — common in DEX swaps)
        for t in internal_transfers.get(h, []):
            # Only include if it involves our address
            if t.from_address == addr or t.to_address == addr:
                transfers.append(t)

        # ERC-20 token transfers
        transfers.extend(token_transfers.get(h, []))

        # Skip entirely if nothing involves our address
        involved = any(
            t.from_address == addr or t.to_address == addr for t in transfers
        )
        if not involved and not (meta.get("from") == addr or meta.get("to") == addr):
            continue

        groups[h] = {"meta": meta, "transfers": transfers}

    return groups
