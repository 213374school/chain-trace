"""Bitcoin transaction fetcher via mempool.space API."""
import time
import requests
import sqlite3
from decimal import Decimal
from datetime import datetime
from typing import Optional

from chain_trace.db.cache import cached_get
from chain_trace.models import TxEvent, TxType, Chain, TokenTransfer
from chain_trace.chains.bitcoin.change_detect import detect_change_outputs

BASE = "https://mempool.space/api"
_SLEEP = 0.1


def _get(path: str, params: dict | None = None) -> dict | list:
    time.sleep(_SLEEP)
    resp = requests.get(f"{BASE}{path}", params=params, timeout=20)
    resp.raise_for_status()
    return resp.json()


def _get_address_info(conn: sqlite3.Connection, address: str) -> dict:
    def fetch():
        return _get(f"/address/{address}")
    return cached_get(conn, "btc:address", {"address": address}, fetch,
                      is_historical=False, ttl=3600)


def _get_txs_page(conn: sqlite3.Connection, address: str,
                  after_txid: str | None = None) -> list:
    """Fetch one page of transactions (up to 25) for an address."""
    params_key = {"address": address, "after": after_txid or ""}

    def fetch():
        path = f"/address/{address}/txs"
        if after_txid:
            path += f"/chain/{after_txid}"
        return _get(path)

    # Only cache if we're paginating past the first page (first page has recent txs)
    return cached_get(conn, "btc:txs", params_key, fetch,
                      is_historical=bool(after_txid), ttl=300)


def _parse_tx(tx: dict, address: str) -> TxEvent | None:
    """Convert a raw mempool.space tx dict into a TxEvent."""
    confirmed = tx.get("status", {}).get("confirmed", False)
    block_time = tx.get("status", {}).get("block_time")
    block_height = tx.get("status", {}).get("block_height", 0)

    if confirmed and block_time:
        ts = datetime.utcfromtimestamp(block_time)
    else:
        ts = datetime.utcnow()
        block_height = 0

    # Compute value flows for our address
    value_in = sum(
        o.get("value", 0)
        for o in tx.get("vout", [])
        if o.get("scriptpubkey_address") == address
    )
    value_out = sum(
        inp.get("prevout", {}).get("value", 0)
        for inp in tx.get("vin", [])
        if inp.get("prevout", {}).get("scriptpubkey_address") == address
    )

    net_sat = value_in - value_out
    if net_sat == 0:
        return None

    net_btc = Decimal(net_sat) / Decimal(10**8)

    if net_sat > 0:
        # Received — find main sender (first vin that's not our address)
        counterparty = next(
            (
                inp["prevout"]["scriptpubkey_address"]
                for inp in tx.get("vin", [])
                if inp.get("prevout", {}).get("scriptpubkey_address") != address
                and inp.get("prevout", {}).get("scriptpubkey_address")
            ),
            None,
        )
        return TxEvent(
            tx_hash=tx["txid"],
            chain=Chain.BTC,
            block=block_height,
            timestamp=ts,
            kind=TxType.RECEIVE,
            net_flows={"BTC": net_btc},
            counterparty=counterparty,
            raw_transfers=[
                TokenTransfer(
                    from_address=counterparty or "unknown",
                    to_address=address,
                    asset_symbol="BTC",
                    asset_address=None,
                    amount=net_btc,
                )
            ],
        )
    else:
        # Sent — find main recipient(s), detect change outputs
        vouts = tx.get("vout", [])
        change_flags = detect_change_outputs(tx, address)

        # Real recipients: non-change outputs, not back to us
        recipients = [
            o
            for i, o in enumerate(vouts)
            if o.get("scriptpubkey_address")
            and o["scriptpubkey_address"] != address
            and not change_flags.get(i, False)
        ]

        # Main counterparty: largest non-change output
        main_recipient = None
        if recipients:
            main_recipient = max(
                recipients, key=lambda o: o.get("value", 0)
            ).get("scriptpubkey_address")

        has_change = any(change_flags.values())

        return TxEvent(
            tx_hash=tx["txid"],
            chain=Chain.BTC,
            block=block_height,
            timestamp=ts,
            kind=TxType.SEND,
            net_flows={"BTC": net_btc},
            counterparty=main_recipient,
            has_change_output=has_change,
            raw_transfers=[
                TokenTransfer(
                    from_address=address,
                    to_address=o.get("scriptpubkey_address") or "unknown",
                    asset_symbol="BTC",
                    asset_address=None,
                    amount=Decimal(o["value"]) / Decimal(10**8),
                )
                for o in vouts
                if o.get("scriptpubkey_address") and o["scriptpubkey_address"] != address
            ],
        )


def get_tx_events(
    conn: sqlite3.Connection,
    address: str,
    limit: int = 100,
    from_ts: Optional[int] = None,
    to_ts: Optional[int] = None,
    dust_btc: float = 0.00001,
) -> list[TxEvent]:
    """Fetch and parse BTC transactions for an address, with date filtering."""
    events: list[TxEvent] = []
    last_txid: str | None = None

    while len(events) < limit:
        txs = _get_txs_page(conn, address, last_txid)
        if not txs:
            break

        for tx in txs:
            # Date filtering: mempool.space returns newest first
            block_time = tx.get("status", {}).get("block_time")
            if to_ts and block_time and block_time > to_ts:
                continue  # too recent, skip
            if from_ts and block_time and block_time < from_ts:
                return events  # too old, stop (results are in reverse chron order)

            event = _parse_tx(tx, address)
            if event is None:
                continue

            # Dust filter
            btc_amount = abs(list(event.net_flows.values())[0])
            if float(btc_amount) < dust_btc:
                continue

            events.append(event)
            if len(events) >= limit:
                break

        if len(txs) < 25:
            break  # last page

        last_txid = txs[-1]["txid"]

    return events


def get_address_tx_count(conn: sqlite3.Connection, address: str) -> int:
    """Return total tx count for traceability scoring."""
    info = _get_address_info(conn, address)
    chain_stats = info.get("chain_stats", {})
    mempool_stats = info.get("mempool_stats", {})
    return chain_stats.get("tx_count", 0) + mempool_stats.get("tx_count", 0)
