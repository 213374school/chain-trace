"""Rich console rendering for transaction events."""
from decimal import Decimal
from datetime import datetime
from typing import Optional
import json

from rich.console import Console
from rich.table import Table
from rich import box
from rich.text import Text

from chain_trace.models import TxEvent, TxType, TraceScore, Chain

console = Console()

# ── Colour scheme ─────────────────────────────────────────────────────────────

_TYPE_COLOR = {
    TxType.RECEIVE:   "green",
    TxType.SEND:      "red",
    TxType.TRANSFER:  "red",
    TxType.SWAP:      "blue",
    TxType.WRAP:      "yellow",
    TxType.UNWRAP:    "yellow",
    TxType.LIQUIDITY: "magenta",
    TxType.CONTRACT:  "white",
}

_SCORE_COLOR = {
    TraceScore.PERSONAL:     "green",
    TraceScore.CONTRACT:     "cyan",
    TraceScore.DEX:          "blue",
    TraceScore.BRIDGE:       "yellow",
    TraceScore.CEX:          "red",
    TraceScore.HIGH_TRAFFIC: "dark_orange",
    TraceScore.UNKNOWN:      "bright_black",
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_amount(amount: Decimal, symbol: str) -> str:
    if abs(amount) >= 1000:
        return f"{amount:,.2f} {symbol}"
    elif abs(amount) >= 1:
        return f"{amount:.4f} {symbol}"
    else:
        return f"{amount:.6f} {symbol}"


def _fmt_flows(net_flows: dict[str, Decimal], prefix: bool = True) -> str:
    parts = []
    for symbol, amount in net_flows.items():
        sign = "+" if amount > 0 else ""
        parts.append(f"{sign}{_fmt_amount(amount, symbol)}")
    return "  ".join(parts)


def _fmt_flows_table(net_flows: dict[str, Decimal]) -> str:
    """Format net flows for table display: show in/out on separate tokens."""
    out_parts = []
    in_parts = []
    for symbol, amount in net_flows.items():
        if amount < 0:
            out_parts.append(_fmt_amount(abs(amount), symbol))
        else:
            in_parts.append(_fmt_amount(amount, symbol))

    if out_parts and in_parts:
        return f"{', '.join(out_parts)} → {', '.join(in_parts)}"
    elif out_parts:
        return f"out  {', '.join(out_parts)}"
    elif in_parts:
        return f"in   {', '.join(in_parts)}"
    return ""


def _short_hash(h: str) -> str:
    return h[:6] + "…" + h[-4:] if len(h) > 12 else h


def _short_addr(addr: str) -> str:
    if not addr:
        return "—"
    if addr.startswith("0x") and len(addr) == 42:
        return addr[:8] + "…" + addr[-4:]
    if len(addr) > 16:
        return addr[:8] + "…" + addr[-6:]
    return addr


def _fmt_counterparty(event: TxEvent, label_fn) -> Text:
    if not event.counterparty:
        return Text("—", style="bright_black")

    addr = event.counterparty
    label = event.counterparty_label or label_fn(addr, event.chain.value)
    score = event.counterparty_score

    display = f"{_short_addr(addr)}"
    if label:
        display = f"{_short_addr(addr)}  {label}"

    t = Text(display)
    if score:
        color = _SCORE_COLOR.get(score.score, "white")
        badge = score.badge()
        t.append(f"\n{badge}", style=color)
    elif label:
        # Infer rough color from known label category
        pass
    return t


def _fmt_details(event: TxEvent) -> Text:
    t = Text()
    kind = event.kind

    if kind == TxType.SWAP:
        flows_str = _fmt_flows_table(event.net_flows)
        t.append(flows_str)
        if event.dex_name:
            t.append(f"\n  via {event.dex_name}", style="bright_black")
        if event.hops and len(event.hops) > 2:
            t.append(f"\n  hops: {' → '.join(event.hops)}", style="bright_black")

    elif kind in (TxType.WRAP, TxType.UNWRAP):
        flows_str = _fmt_flows_table(event.net_flows)
        t.append(flows_str)

    elif kind == TxType.LIQUIDITY:
        action = event.lp_action or "?"
        flows_str = _fmt_flows_table(event.net_flows)
        t.append(f"{action}:  {flows_str}")
        if event.pool_label:
            t.append(f"\n  {event.pool_label}", style="bright_black")

    elif kind in (TxType.TRANSFER, TxType.SEND, TxType.RECEIVE):
        flows_str = _fmt_flows_table(event.net_flows)
        t.append(flows_str)

    elif kind == TxType.CONTRACT:
        flows_str = _fmt_flows(event.net_flows, prefix=True)
        t.append(f"net: {flows_str}")
        n = len(event.raw_transfers)
        if n:
            t.append(f"  ({n} transfer{'s' if n != 1 else ''})", style="bright_black")

    if event.usd_total:
        t.append(f"\n  ≈ ${event.usd_total:,.2f}", style="bright_black")

    return t


# ── Main rendering function ───────────────────────────────────────────────────

def print_events(
    events: list[TxEvent],
    address: str,
    chain: Chain,
    label_fn,
    as_json: bool = False,
    from_date: str | None = None,
    to_date: str | None = None,
) -> None:
    if as_json:
        from chain_trace.output.json_output import events_to_json
        print(events_to_json(events, address, chain, from_date, to_date))
        return

    if not events:
        console.print("[yellow]No transactions found.[/yellow]")
        return

    # Header
    addr_label = label_fn(address, chain.value)
    label_str = f"  ({addr_label})" if addr_label else ""
    period_str = " → ".join(filter(None, [from_date, to_date])) or "all time"
    console.print(
        f"  [bold]Address[/bold]  [cyan]{address}{label_str}[/cyan]   "
        f"[bold]Chain[/bold]  [cyan]{chain.value.upper()}[/cyan]"
    )
    console.print(
        f"  [bold]Period[/bold]   {period_str}   "
        f"[bold]Showing[/bold]  {len(events)} transaction{'s' if len(events) != 1 else ''}"
    )
    console.print()

    table = Table(
        box=box.SIMPLE_HEAD,
        show_header=True,
        header_style="bold",
        padding=(0, 1),
        expand=False,
    )
    table.add_column("TIMESTAMP", style="bright_black", no_wrap=True, min_width=17)
    table.add_column("TYPE", no_wrap=True, min_width=9)
    table.add_column("DETAILS", min_width=30)
    table.add_column("COUNTERPARTY", min_width=20)
    table.add_column("TX", style="bright_black", no_wrap=True)

    for event in events:
        ts_str = event.timestamp.strftime("%Y-%m-%d %H:%M")
        kind = event.kind
        color = _TYPE_COLOR.get(kind, "white")
        type_text = Text(kind.value, style=f"bold {color}")
        details = _fmt_details(event)
        cp_text = _fmt_counterparty(event, label_fn)
        tx_str = _short_hash(event.tx_hash)

        table.add_row(ts_str, type_text, details, cp_text, tx_str)

    console.print(table)


def print_single_tx(event: TxEvent, label_fn, as_json: bool = False) -> None:
    """Detailed view for a single transaction (trace tx command)."""
    if as_json:
        from chain_trace.output.json_output import event_to_dict
        import json
        print(json.dumps(event_to_dict(event), indent=2, default=str))
        return

    color = _TYPE_COLOR.get(event.kind, "white")
    console.print(f"\n  [bold]TX Hash[/bold]   [cyan]{event.tx_hash}[/cyan]")
    console.print(f"  [bold]Type[/bold]      [{color}]{event.kind.value}[/{color}]")
    console.print(f"  [bold]Time[/bold]      {event.timestamp.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    console.print(f"  [bold]Block[/bold]     {event.block:,}")
    if event.dex_name:
        console.print(f"  [bold]DEX[/bold]       {event.dex_name}")
    if event.lp_action:
        console.print(f"  [bold]LP Action[/bold] {event.lp_action}")
    console.print()

    # Net flows
    console.print("  [bold]Net Flows[/bold]")
    for symbol, amount in event.net_flows.items():
        sign = "+" if amount > 0 else ""
        color_f = "green" if amount > 0 else "red"
        console.print(
            f"    [{color_f}]{sign}{_fmt_amount(amount, symbol)}[/{color_f}]"
        )
    console.print()

    # All transfers
    if event.raw_transfers:
        console.print("  [bold]All Transfers[/bold]")
        for t in event.raw_transfers:
            from_label = label_fn(t.from_address, event.chain.value) or _short_addr(t.from_address)
            to_label = label_fn(t.to_address, event.chain.value) or _short_addr(t.to_address)
            console.print(
                f"    {_fmt_amount(t.amount, t.asset_symbol)}  "
                f"[bright_black]{from_label} → {to_label}[/bright_black]"
            )
    console.print()
