"""Address-label lookups via the Chainbase Web3 Data API.

API reference: https://docs.chainbase.com/reference/get_account_labels
Auth: pass your API key as the 'x-api-key' request header.
Set up: trace config set chainbase_key YOUR_KEY
"""
import sqlite3
import requests
from typing import Optional

from chain_trace.db.cache import cached_get

CHAINBASE_BASE = "https://api.chainbase.com/v1"

# Chainbase numeric chain IDs for chains this tool supports
_CHAIN_IDS: dict[str, int] = {
    "eth": 1,
    # Bitcoin is not supported by the Chainbase address-labels endpoint
}

# Keywords inside Chainbase label strings → internal category names
_CATEGORY_KEYWORDS: list[tuple[str, str]] = [
    ("exchange", "exchange"),
    (" cex",     "exchange"),
    ("binance",  "exchange"),
    ("coinbase", "exchange"),
    ("kraken",   "exchange"),
    ("okx",      "exchange"),
    ("dex",      "dex"),
    ("swap",     "dex"),
    ("uniswap",  "dex"),
    ("sushiswap","dex"),
    ("curve",    "dex"),
    ("bridge",   "bridge"),
    ("mixer",    "mixer"),
    ("tornado",  "mixer"),
    ("token",    "token"),
    ("miner",    "miner"),
]

# Cache address-label responses for 7 days; entity names rarely change
_TTL = 86_400 * 7


def fetch_label(
    conn: sqlite3.Connection,
    address: str,
    chain: str,
    api_key: str,
) -> Optional[dict]:
    """Query Chainbase for address entity labels.

    Returns ``{"name": str, "category": str | None}`` when a label is found,
    or ``None`` when the address is unknown or the API is unavailable.

    Raw API responses are stored in the ``api_cache`` table and reused for
    ``_TTL`` seconds so repeat lookups never hit the network.
    """
    chain_id = _CHAIN_IDS.get(chain)
    if chain_id is None:
        return None

    endpoint = f"{CHAINBASE_BASE}/account/labels"
    params: dict = {"chain_id": chain_id, "address": address.lower()}

    def _do_request():
        resp = requests.get(
            endpoint,
            params=params,
            headers={"x-api-key": api_key, "accept": "application/json"},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    try:
        data = cached_get(conn, endpoint, params, _do_request, ttl=_TTL)
    except Exception:
        return None

    if not data or data.get("code") != 0:
        return None

    raw = data.get("data") or []
    if not raw:
        return None

    # Chainbase returns a list of label strings; the first is the entity name
    if not isinstance(raw, list):
        return None
    labels = [str(l).strip() for l in raw if l]
    if not labels:
        return None

    name = labels[0]
    category = _infer_category(labels)
    return {"name": name, "category": category}


def _infer_category(labels: list[str]) -> Optional[str]:
    """Return the first matching internal category from a list of label strings."""
    joined = " ".join(labels).lower()
    for keyword, category in _CATEGORY_KEYWORDS:
        if keyword in joined:
            return category
    return None
