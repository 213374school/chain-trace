import hashlib
import json
import time
import sqlite3
from typing import Any, Callable


def _make_key(endpoint: str, params: dict) -> str:
    params_str = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    raw = f"{endpoint}:{params_str}"
    if len(raw) > 200:
        return hashlib.sha256(raw.encode()).hexdigest()
    return raw


def cached_get(
    conn: sqlite3.Connection,
    endpoint: str,
    params: dict,
    fetch_fn: Callable[[], Any],
    is_historical: bool = False,
    ttl: int = 3600,
) -> Any:
    """Fetch from cache or call fetch_fn and store result.

    is_historical=True means the data will never change (confirmed blocks,
    historical prices) — stored with NULL expires_at (never expires).
    """
    key = _make_key(endpoint, params)

    row = conn.execute(
        "SELECT response_json, expires_at FROM api_cache WHERE cache_key = ?",
        (key,),
    ).fetchone()

    if row:
        expires = row["expires_at"]
        if expires is None or expires > time.time():
            return json.loads(row["response_json"])

    data = fetch_fn()
    expires_at = None if is_historical else int(time.time()) + ttl

    conn.execute(
        "INSERT OR REPLACE INTO api_cache "
        "(cache_key, response_json, fetched_at, expires_at, endpoint) "
        "VALUES (?, ?, ?, ?, ?)",
        (key, json.dumps(data), int(time.time()), expires_at, endpoint),
    )
    conn.commit()
    return data


def invalidate(conn: sqlite3.Connection, endpoint: str, params: dict) -> None:
    key = _make_key(endpoint, params)
    conn.execute("DELETE FROM api_cache WHERE cache_key = ?", (key,))
    conn.commit()
