import json
import sqlite3
from pathlib import Path
from typing import Optional

_CATALOG_PATH = Path(__file__).parent / "addresses.json"


def load_catalog(conn: sqlite3.Connection) -> int:
    """Load bundled catalog into labels table. Idempotent (INSERT OR IGNORE).
    Returns count of newly inserted entries."""
    entries = json.loads(_CATALOG_PATH.read_text())
    count = 0
    for entry in entries:
        address = entry["address"]
        if address.startswith("0x"):
            address = address.lower()
        cursor = conn.execute(
            "INSERT OR IGNORE INTO labels (address, chain, name, category, source) "
            "VALUES (?, ?, ?, ?, 'catalog')",
            (address, entry["chain"], entry["name"], entry.get("category")),
        )
        count += cursor.rowcount
    conn.commit()
    return count


def lookup(conn: sqlite3.Connection, address: str, chain: str) -> Optional[dict]:
    """Look up a label — checks both exact chain and 'any'. Used by classifier."""
    addr = address.lower() if address.startswith("0x") else address
    row = conn.execute(
        "SELECT name, category FROM labels "
        "WHERE address = ? AND (chain = ? OR chain = 'any') "
        "ORDER BY CASE chain WHEN ? THEN 0 ELSE 1 END LIMIT 1",
        (addr, chain, chain),
    ).fetchone()
    return dict(row) if row else None


def get_dex_routers(conn: sqlite3.Connection) -> dict[str, str]:
    """Return {address: name} for all DEX router entries."""
    rows = conn.execute(
        "SELECT address, name FROM labels WHERE category = 'dex' AND chain = 'eth'"
    ).fetchall()
    return {r["address"]: r["name"] for r in rows}
