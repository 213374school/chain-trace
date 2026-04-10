"""Etherscan API wrapper with rate limiting and caching."""
import time
import requests
import sqlite3
from chain_trace.db.cache import cached_get

ETHERSCAN_BASE = "https://api.etherscan.io/v2/api"
_SLEEP = 0.25  # 4 req/s — safely under Etherscan free tier limit of 5/s


def _get(params: dict, api_key: str) -> dict:
    time.sleep(_SLEEP)
    params["apikey"] = api_key
    params.setdefault("chainid", "1")  # Ethereum mainnet (V2 API requires chainid)
    resp = requests.get(ETHERSCAN_BASE, params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    msg = data.get("message", "")
    if data.get("status") == "0" and "No transactions" in msg:
        return {"result": []}
    if data.get("status") == "0":
        raise RuntimeError(
            f"Etherscan error [{data.get('message')}]: {data.get('result')}"
        )
    return data


def get_normal_txs(
    conn: sqlite3.Connection,
    address: str,
    api_key: str,
    start_block: int = 0,
    end_block: int = 99999999,
    page: int = 1,
    offset: int = 2000,
) -> list[dict]:
    params_key = {
        "address": address.lower(),
        "startblock": start_block,
        "endblock": end_block,
        "page": page,
        "offset": offset,
    }

    def fetch():
        data = _get(
            {
                "module": "account",
                "action": "txlist",
                "address": address,
                "startblock": start_block,
                "endblock": end_block,
                "sort": "desc",
                "page": page,
                "offset": offset,
            },
            api_key,
        )
        return data.get("result", [])

    return cached_get(
        conn, "eth:txlist", params_key, fetch, is_historical=(end_block < 99999999)
    )


def get_token_transfers(
    conn: sqlite3.Connection,
    address: str,
    api_key: str,
    start_block: int = 0,
    end_block: int = 99999999,
    page: int = 1,
    offset: int = 2000,
    contract_address: str | None = None,
) -> list[dict]:
    params_key: dict = {
        "address": address.lower(),
        "startblock": start_block,
        "endblock": end_block,
        "page": page,
        "offset": offset,
    }
    if contract_address:
        params_key["contract"] = contract_address.lower()

    def fetch():
        p: dict = {
            "module": "account",
            "action": "tokentx",
            "address": address,
            "startblock": start_block,
            "endblock": end_block,
            "sort": "desc",
            "page": page,
            "offset": offset,
        }
        if contract_address:
            p["contractaddress"] = contract_address
        data = _get(p, api_key)
        return data.get("result", [])

    return cached_get(
        conn,
        "eth:tokentx",
        params_key,
        fetch,
        is_historical=(end_block < 99999999),
    )


def get_internal_txs(
    conn: sqlite3.Connection,
    address: str,
    api_key: str,
    start_block: int = 0,
    end_block: int = 99999999,
    page: int = 1,
    offset: int = 2000,
) -> list[dict]:
    params_key = {
        "address": address.lower(),
        "startblock": start_block,
        "endblock": end_block,
        "page": page,
        "offset": offset,
    }

    def fetch():
        data = _get(
            {
                "module": "account",
                "action": "txlistinternal",
                "address": address,
                "startblock": start_block,
                "endblock": end_block,
                "sort": "desc",
                "page": page,
                "offset": offset,
            },
            api_key,
        )
        return data.get("result", [])

    return cached_get(
        conn,
        "eth:txlistinternal",
        params_key,
        fetch,
        is_historical=(end_block < 99999999),
    )


def get_block_by_timestamp(
    conn: sqlite3.Connection,
    timestamp: int,
    api_key: str,
    closest: str = "before",
) -> int:
    """Convert Unix timestamp to the nearest block number."""
    def fetch():
        data = _get(
            {
                "module": "block",
                "action": "getblocknobytime",
                "timestamp": timestamp,
                "closest": closest,
            },
            api_key,
        )
        return {"block": int(data["result"])}

    result = cached_get(
        conn,
        "eth:getblocknobytime",
        {"timestamp": timestamp, "closest": closest},
        fetch,
        is_historical=True,
    )
    return result["block"]


def check_is_contract(conn: sqlite3.Connection, address: str, api_key: str) -> bool:
    """Returns True if the address has contract code deployed."""
    def fetch():
        data = _get(
            {
                "module": "proxy",
                "action": "eth_getCode",
                "address": address,
                "tag": "latest",
            },
            api_key,
        )
        return {"code": data.get("result", "0x")}

    result = cached_get(
        conn,
        "eth:getCode",
        {"address": address.lower()},
        fetch,
        is_historical=True,
    )
    code = result.get("code", "0x")
    return bool(code and code not in ("0x", "0x0"))


def get_address_tx_count(conn: sqlite3.Connection, address: str, api_key: str) -> int:
    """Returns total transaction count for traceability scoring (cached 1hr)."""
    def fetch():
        # Use txlist with page=1 offset=1 and check totalCount header
        # Etherscan doesn't return total count directly; we fetch page 1 and
        # if it returns a full page (offset items), the address is high-traffic.
        # As a heuristic, we fetch offset=10000 page=1 and count.
        data = _get(
            {
                "module": "account",
                "action": "txlist",
                "address": address,
                "startblock": 0,
                "endblock": 99999999,
                "sort": "asc",
                "page": 1,
                "offset": 10000,
            },
            api_key,
        )
        results = data.get("result", [])
        # If we got 10000 items, actual count is >= 10000 (HIGH_TRAFFIC territory)
        return {"count": len(results), "capped": len(results) == 10000}

    result = cached_get(
        conn,
        "eth:txcount",
        {"address": address.lower()},
        fetch,
        is_historical=False,
        ttl=3600,
    )
    # If capped, return a very large number to trigger HIGH_TRAFFIC
    return 999999 if result.get("capped") else result.get("count", 0)
