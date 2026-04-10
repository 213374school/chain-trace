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
