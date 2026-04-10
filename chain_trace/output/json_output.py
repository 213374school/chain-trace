"""JSON serialization helpers."""
import json
from decimal import Decimal
from datetime import datetime
from chain_trace.models import TxEvent, Chain


def _default(obj):
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.strftime("%Y-%m-%dT%H:%M:%SZ")
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def event_to_dict(event: TxEvent) -> dict:
    return {
        "tx_hash": event.tx_hash,
        "chain": event.chain.value,
        "block": event.block,
        "timestamp": event.timestamp,
        "kind": event.kind.value,
        "net_flows": {k: str(v) for k, v in event.net_flows.items()},
        "counterparty": event.counterparty,
        "counterparty_label": event.counterparty_label,
        "counterparty_score": (
            {
                "score": event.counterparty_score.score.value,
                "tx_count": event.counterparty_score.tx_count,
                "label": event.counterparty_score.label,
                "category": event.counterparty_score.category,
            }
            if event.counterparty_score
            else None
        ),
        "dex_name": event.dex_name,
        "hops": event.hops,
        "lp_action": event.lp_action,
        "pool_label": event.pool_label,
        "has_change_output": event.has_change_output,
        "usd_total": str(event.usd_total) if event.usd_total else None,
    }


def events_to_json(
    events: list[TxEvent],
    address: str,
    chain: Chain,
    from_date: str | None = None,
    to_date: str | None = None,
) -> str:
    payload = {
        "meta": {
            "command": "trace",
            "address": address,
            "chain": chain.value,
            "filters": {
                "from": from_date,
                "to": to_date,
            },
            "generated_at": datetime.utcnow(),
            "count": len(events),
        },
        "data": [event_to_dict(e) for e in events],
    }
    return json.dumps(payload, indent=2, default=_default)
