"""Historical USD prices via CoinGecko free API."""
import time
import requests
import sqlite3
from typing import Optional

from chain_trace.db.prices import get_price, set_price

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
_SLEEP = 1.5  # CoinGecko free tier: ~10–30 req/min


def get_historical_price(
    conn: sqlite3.Connection,
    coin_id: str,
    date_str: str,  # 'YYYY-MM-DD'
) -> Optional[float]:
    """Fetch USD price for coin on a given date. Cached permanently."""
    cached = get_price(conn, coin_id, date_str)
    if cached is not None:
        return cached

    # CoinGecko expects DD-MM-YYYY
    parts = date_str.split("-")
    if len(parts) == 3:
        cg_date = f"{parts[2]}-{parts[1]}-{parts[0]}"
    else:
        return None

    try:
        time.sleep(_SLEEP)
        resp = requests.get(
            f"{COINGECKO_BASE}/coins/{coin_id}/history",
            params={"date": cg_date, "localization": "false"},
            timeout=15,
        )
        if resp.status_code == 429:
            time.sleep(60)
            return None
        resp.raise_for_status()
        data = resp.json()
        price = (
            data.get("market_data", {})
            .get("current_price", {})
            .get("usd")
        )
        if price is not None:
            set_price(conn, coin_id, date_str, float(price))
        return price
    except Exception:
        return None
