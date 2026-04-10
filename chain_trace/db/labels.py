import sqlite3
from typing import Optional


def _normalise(address: str) -> str:
    """Lowercase ETH addresses; leave BTC addresses as-is."""
    if address.startswith("0x"):
        return address.lower()
    return address


def get_label(
    conn: sqlite3.Connection,
    address: str,
    chain: str,
) -> Optional[dict]:
    addr = _normalise(address)
    # Prefer exact chain match, fall back to 'any'
    row = conn.execute(
        "SELECT name, category, source, notes FROM labels "
        "WHERE address = ? AND chain = ?",
        (addr, chain),
    ).fetchone()
    if not row:
        row = conn.execute(
            "SELECT name, category, source, notes FROM labels "
            "WHERE address = ? AND chain = 'any'",
            (addr,),
        ).fetchone()
    return dict(row) if row else None


def set_label(
    conn: sqlite3.Connection,
    address: str,
    name: str,
    chain: str = "any",
    category: Optional[str] = None,
    source: str = "user",
    notes: Optional[str] = None,
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO labels (address, chain, name, category, source, notes) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (_normalise(address), chain, name, category, source, notes),
    )
    conn.commit()


def remove_label(
    conn: sqlite3.Connection,
    address: str,
    chain: str = "any",
) -> bool:
    """Remove a user-defined label. Returns True if a row was deleted."""
    cursor = conn.execute(
        "DELETE FROM labels WHERE address = ? AND chain = ? AND source = 'user'",
        (_normalise(address), chain),
    )
    conn.commit()
    return cursor.rowcount > 0


def list_labels(
    conn: sqlite3.Connection,
    chain: Optional[str] = None,
    category: Optional[str] = None,
    source: Optional[str] = None,
) -> list[dict]:
    query = "SELECT address, chain, name, category, source, notes FROM labels WHERE 1=1"
    params: list = []
    if chain:
        query += " AND chain = ?"
        params.append(chain)
    if category:
        query += " AND category = ?"
        params.append(category)
    if source:
        query += " AND source = ?"
        params.append(source)
    query += " ORDER BY chain, name"
    return [dict(r) for r in conn.execute(query, params).fetchall()]


def resolve_label(
    conn: sqlite3.Connection,
    address: str,
    chain: str,
) -> Optional[dict]:
    """Resolve a label for an address: local DB first, Chainbase API as fallback.

    If Chainbase returns a result it is persisted to the ``labels`` table with
    ``source='chainbase'`` so subsequent calls are served locally without
    another network round-trip.

    Chainbase lookup is skipped when ``chainbase_key`` is not configured.
    """
    result = get_label(conn, address, chain)
    if result:
        return result

    row = conn.execute(
        "SELECT value FROM config WHERE key = 'chainbase_key'"
    ).fetchone()
    api_key = row["value"] if row else ""
    if not api_key:
        return None

    from chain_trace.labels.chainbase import fetch_label
    fetched = fetch_label(conn, address, chain, api_key)
    if fetched:
        set_label(
            conn,
            address,
            fetched["name"],
            chain=chain,
            category=fetched.get("category"),
            source="chainbase",
        )
        return fetched
    return None
