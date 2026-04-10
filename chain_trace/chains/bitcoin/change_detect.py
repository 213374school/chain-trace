"""Bitcoin change output detection heuristics."""
from decimal import Decimal


def _is_round_btc(satoshis: int) -> bool:
    """Returns True if amount looks like an intentional payment (round number)."""
    btc = satoshis / 1e8
    # Check if it's round at common denominations
    for precision in (1, 0.5, 0.1, 0.01, 0.001):
        if abs(btc % precision) < 1e-9:
            return True
    return False


def _addr_type(address: str) -> str:
    """Return address type: 'bech32', 'p2sh', 'legacy', or 'unknown'."""
    if address.startswith("bc1q") or address.startswith("bc1p"):
        return "bech32"
    if address.startswith("3"):
        return "p2sh"
    if address.startswith("1"):
        return "legacy"
    return "unknown"


def detect_change_outputs(tx: dict, address: str) -> dict[int, bool]:
    """
    For an outbound tx (address is in vin), score each vout for being change.

    Returns {vout_index: is_change (bool)}.

    Heuristics (scored):
      H1  non-round amount                      +1
      H3  remainder-like (non-round, not largest output)  +2
      H4  same address type as input             +1

    Note: H2 (single-use address check) would require an API call per output
    and is intentionally omitted here to keep this function fast/offline.
    Traceability scoring handles per-address freshness separately.

    is_change = score >= 3
    """
    vouts = tx.get("vout", [])
    vin_addresses = [
        inp.get("prevout", {}).get("scriptpubkey_address", "")
        for inp in tx.get("vin", [])
    ]
    # Primary input type (most common)
    input_types = [_addr_type(a) for a in vin_addresses if a]
    primary_input_type = max(set(input_types), key=input_types.count) if input_types else "unknown"

    # Outputs that aren't back to us
    candidate_outputs = [
        (i, o)
        for i, o in enumerate(vouts)
        if o.get("scriptpubkey_address") and o["scriptpubkey_address"] != address
    ]

    if len(candidate_outputs) <= 1:
        # Single output → definitely a payment, not change
        return {i: False for i, _ in candidate_outputs}

    max_value = max((o.get("value", 0) for _, o in candidate_outputs), default=0)
    result: dict[int, bool] = {}

    for i, o in candidate_outputs:
        val = o.get("value", 0)
        out_addr = o.get("scriptpubkey_address", "")
        score = 0

        # H1: non-round amount
        if not _is_round_btc(val):
            score += 1

        # H3: smaller than largest and non-round (remainder-like)
        if val < max_value and not _is_round_btc(val):
            score += 2

        # H4: same address type as inputs
        if _addr_type(out_addr) == primary_input_type:
            score += 1

        result[i] = score >= 3

    return result
