import sqlite3
from pathlib import Path

DEFAULT_DB = Path.home() / ".chain-trace" / "data.db"
_SCHEMA = Path(__file__).parent / "schema.sql"

_CONFIG_DEFAULTS = [
    ("dust_threshold_btc",    "0.00001"),
    ("dust_threshold_eth",    "0.0001"),
    ("high_traffic_threshold","10000"),
    ("etherscan_key",         ""),
    ("chainbase_key",         ""),
]


def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else DEFAULT_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    _apply_schema(conn)
    _insert_defaults(conn)
    return conn


def _apply_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA.read_text())


def _insert_defaults(conn: sqlite3.Connection) -> None:
    for key, value in _CONFIG_DEFAULTS:
        conn.execute(
            "INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)",
            (key, value),
        )
    conn.commit()
