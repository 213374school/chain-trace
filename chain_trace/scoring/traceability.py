"""Address traceability scoring."""
import time
import sqlite3
from chain_trace.models import TraceScore, TraceabilityResult, Chain


def score_address(
    conn: sqlite3.Connection,
    address: str,
    chain: Chain,
    api_key: str = "",
) -> TraceabilityResult:
    """Score an address for traceability. Cached for 1 hour."""
    addr = address.lower() if address.startswith("0x") else address
    chain_val = chain.value

    # Check traceability cache
    row = conn.execute(
        "SELECT score, tx_count, expires_at FROM traceability_cache "
        "WHERE address = ? AND chain = ?",
        (addr, chain_val),
    ).fetchone()
    if row and row["expires_at"] > time.time():
        label_row = conn.execute(
            "SELECT name, category FROM labels WHERE address = ? AND (chain = ? OR chain = 'any')",
            (addr, chain_val),
        ).fetchone()
        return TraceabilityResult(
            address=addr,
            chain=chain,
            score=TraceScore(row["score"]),
            tx_count=row["tx_count"],
            label=label_row["name"] if label_row else None,
            category=label_row["category"] if label_row else None,
        )

    # Check labels table (catalog entries take priority)
    label_row = conn.execute(
        "SELECT name, category, source FROM labels "
        "WHERE address = ? AND (chain = ? OR chain = 'any') "
        "ORDER BY CASE source WHEN 'catalog' THEN 0 ELSE 1 END LIMIT 1",
        (addr, chain_val),
    ).fetchone()

    label = label_row["name"] if label_row else None
    category = label_row["category"] if label_row else None

    score = _score_from_category(category)

    tx_count = None

    # If not resolved from catalog, fetch tx count
    if score == TraceScore.UNKNOWN and api_key:
        tx_count = _fetch_tx_count(conn, addr, chain, api_key)
        threshold = int(
            conn.execute(
                "SELECT value FROM config WHERE key = 'high_traffic_threshold'"
            ).fetchone()["value"]
        )
        if tx_count >= threshold:
            score = TraceScore.HIGH_TRAFFIC
        elif tx_count <= 10:
            score = TraceScore.PERSONAL

        # ETH: check if it's a contract
        if chain == Chain.ETH and score == TraceScore.UNKNOWN and api_key:
            from chain_trace.chains.ethereum.fetcher import check_is_contract
            if check_is_contract(conn, addr, api_key):
                score = TraceScore.CONTRACT

    # Store in cache
    conn.execute(
        "INSERT OR REPLACE INTO traceability_cache "
        "(address, chain, score, tx_count, fetched_at, expires_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (addr, chain_val, score.value, tx_count, int(time.time()), int(time.time()) + 3600),
    )
    conn.commit()

    return TraceabilityResult(
        address=addr,
        chain=chain,
        score=score,
        tx_count=tx_count,
        label=label,
        category=category,
    )


def _score_from_category(category: str | None) -> TraceScore:
    if category is None:
        return TraceScore.UNKNOWN
    mapping = {
        "exchange": TraceScore.CEX,
        "dex":      TraceScore.DEX,
        "bridge":   TraceScore.BRIDGE,
        "token":    TraceScore.CONTRACT,
        "contract": TraceScore.CONTRACT,
        "lending":  TraceScore.CONTRACT,
        "mixer":    TraceScore.CEX,   # treat mixers as dead ends
        "hacker":   TraceScore.UNKNOWN,
        "historical": TraceScore.UNKNOWN,
    }
    return mapping.get(category, TraceScore.UNKNOWN)


def _fetch_tx_count(
    conn: sqlite3.Connection,
    address: str,
    chain: Chain,
    api_key: str,
) -> int:
    if chain == Chain.ETH:
        from chain_trace.chains.ethereum.fetcher import get_address_tx_count
        return get_address_tx_count(conn, address, api_key)
    else:
        from chain_trace.chains.bitcoin.fetcher import get_address_tx_count as btc_count
        return btc_count(conn, address)
