PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS labels (
    address   TEXT NOT NULL,
    chain     TEXT NOT NULL CHECK(chain IN ('btc', 'eth', 'any')),
    name      TEXT NOT NULL,
    category  TEXT,
    source    TEXT NOT NULL DEFAULT 'user',
    notes     TEXT,
    PRIMARY KEY (address, chain)
);

CREATE TABLE IF NOT EXISTS api_cache (
    cache_key     TEXT    PRIMARY KEY,
    response_json TEXT    NOT NULL,
    fetched_at    INTEGER NOT NULL,
    expires_at    INTEGER,
    endpoint      TEXT
);
CREATE INDEX IF NOT EXISTS idx_api_cache_expires ON api_cache(expires_at);

CREATE TABLE IF NOT EXISTS prices (
    coin_id   TEXT NOT NULL,
    date      TEXT NOT NULL,
    usd_price REAL NOT NULL,
    PRIMARY KEY (coin_id, date)
);

CREATE TABLE IF NOT EXISTS sessions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL UNIQUE,
    created_at INTEGER NOT NULL,
    notes      TEXT
);

CREATE TABLE IF NOT EXISTS session_addresses (
    session_id      INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    address         TEXT    NOT NULL,
    chain           TEXT    NOT NULL CHECK(chain IN ('btc', 'eth')),
    added_at        INTEGER NOT NULL,
    is_dead_end     INTEGER NOT NULL DEFAULT 0,
    dead_end_reason TEXT,
    PRIMARY KEY (session_id, address, chain)
);

CREATE TABLE IF NOT EXISTS traceability_cache (
    address    TEXT    NOT NULL,
    chain      TEXT    NOT NULL,
    score      TEXT    NOT NULL,
    tx_count   INTEGER,
    fetched_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    PRIMARY KEY (address, chain)
);
