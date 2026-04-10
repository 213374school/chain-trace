import sqlite3
import time
from typing import Optional


def create_session(
    conn: sqlite3.Connection,
    name: str,
    notes: Optional[str] = None,
) -> int:
    cursor = conn.execute(
        "INSERT INTO sessions (name, created_at, notes) VALUES (?, ?, ?)",
        (name, int(time.time()), notes),
    )
    conn.commit()
    return cursor.lastrowid


def get_session(conn: sqlite3.Connection, name: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT id, name, created_at, notes FROM sessions WHERE name = ?",
        (name,),
    ).fetchone()
    return dict(row) if row else None


def list_sessions(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT id, name, created_at, notes FROM sessions ORDER BY created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def delete_session(conn: sqlite3.Connection, name: str) -> bool:
    cursor = conn.execute("DELETE FROM sessions WHERE name = ?", (name,))
    conn.commit()
    return cursor.rowcount > 0


def add_address(
    conn: sqlite3.Connection,
    session_id: int,
    address: str,
    chain: str,
) -> None:
    addr = address.lower() if address.startswith("0x") else address
    conn.execute(
        "INSERT OR IGNORE INTO session_addresses "
        "(session_id, address, chain, added_at) VALUES (?, ?, ?, ?)",
        (session_id, addr, chain, int(time.time())),
    )
    conn.commit()


def remove_address(
    conn: sqlite3.Connection,
    session_id: int,
    address: str,
    chain: str,
) -> bool:
    addr = address.lower() if address.startswith("0x") else address
    cursor = conn.execute(
        "DELETE FROM session_addresses WHERE session_id = ? AND address = ? AND chain = ?",
        (session_id, addr, chain),
    )
    conn.commit()
    return cursor.rowcount > 0


def mark_dead_end(
    conn: sqlite3.Connection,
    session_id: int,
    address: str,
    chain: str,
    reason: Optional[str] = None,
) -> None:
    addr = address.lower() if address.startswith("0x") else address
    conn.execute(
        "UPDATE session_addresses SET is_dead_end = 1, dead_end_reason = ? "
        "WHERE session_id = ? AND address = ? AND chain = ?",
        (reason, session_id, addr, chain),
    )
    conn.commit()


def get_session_addresses(
    conn: sqlite3.Connection,
    session_id: int,
    active_only: bool = False,
) -> list[dict]:
    query = (
        "SELECT address, chain, added_at, is_dead_end, dead_end_reason "
        "FROM session_addresses WHERE session_id = ?"
    )
    params: list = [session_id]
    if active_only:
        query += " AND is_dead_end = 0"
    return [dict(r) for r in conn.execute(query, params).fetchall()]
