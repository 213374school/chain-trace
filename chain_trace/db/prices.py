import sqlite3
from typing import Optional


def get_price(conn: sqlite3.Connection, coin_id: str, date: str) -> Optional[float]:
    """Look up cached USD price. date: 'YYYY-MM-DD'"""
    row = conn.execute(
        "SELECT usd_price FROM prices WHERE coin_id = ? AND date = ?",
        (coin_id, date),
    ).fetchone()
    return row["usd_price"] if row else None


def set_price(conn: sqlite3.Connection, coin_id: str, date: str, usd_price: float) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO prices (coin_id, date, usd_price) VALUES (?, ?, ?)",
        (coin_id, date, usd_price),
    )
    conn.commit()
