from dataclasses import dataclass, field
from decimal import Decimal
from datetime import datetime
from enum import Enum
from typing import Optional


class Chain(str, Enum):
    BTC = "btc"
    ETH = "eth"


class TxType(str, Enum):
    RECEIVE   = "RECEIVE"    # inbound transfer
    SEND      = "SEND"       # BTC outbound
    TRANSFER  = "TRANSFER"   # ETH single-asset outbound
    SWAP      = "SWAP"       # DEX swap
    WRAP      = "WRAP"       # ETH → WETH
    UNWRAP    = "UNWRAP"     # WETH → ETH
    LIQUIDITY = "LIQUIDITY"  # LP add/remove
    CONTRACT  = "CONTRACT"   # unclassified multi-transfer


class TraceScore(str, Enum):
    PERSONAL     = "PERSONAL"
    CONTRACT     = "CONTRACT"
    DEX          = "DEX"
    BRIDGE       = "BRIDGE"
    CEX          = "CEX"
    HIGH_TRAFFIC = "HIGH_TRAFFIC"
    UNKNOWN      = "UNKNOWN"


@dataclass
class TokenTransfer:
    """A single asset transfer (native ETH or ERC-20) within a transaction."""
    from_address:  str
    to_address:    str
    asset_symbol:  str            # 'ETH', 'USDC', 'WETH', etc.
    asset_address: Optional[str]  # None for native ETH
    amount:        Decimal
    usd_value:     Optional[Decimal] = None


@dataclass
class TraceabilityResult:
    address:  str
    chain:    Chain
    score:    TraceScore
    tx_count: Optional[int]
    label:    Optional[str]
    category: Optional[str]

    def badge(self) -> str:
        """Short display badge for the score."""
        return {
            TraceScore.PERSONAL:     "[PERSONAL ✓]",
            TraceScore.CONTRACT:     "[CONTRACT]",
            TraceScore.DEX:          "[DEX]",
            TraceScore.BRIDGE:       "[BRIDGE]",
            TraceScore.CEX:          "[CEX — dead end]",
            TraceScore.HIGH_TRAFFIC: "[HIGH_TRAFFIC ?]",
            TraceScore.UNKNOWN:      "[UNKNOWN]",
        }[self.score]

    def color(self) -> str:
        return {
            TraceScore.PERSONAL:     "green",
            TraceScore.CONTRACT:     "cyan",
            TraceScore.DEX:          "blue",
            TraceScore.BRIDGE:       "yellow",
            TraceScore.CEX:          "red",
            TraceScore.HIGH_TRAFFIC: "dark_orange",
            TraceScore.UNKNOWN:      "white",
        }[self.score]


@dataclass
class TxEvent:
    """Unified classified transaction event — ETH or BTC."""
    tx_hash:   str
    chain:     Chain
    block:     int
    timestamp: datetime
    kind:      TxType

    # Net asset flows for queried address: positive = in, negative = out
    net_flows: dict[str, Decimal]  # e.g. {'ETH': Decimal('-1.5'), 'USDC': Decimal('2900')}

    # Counterparty (for TRANSFER / RECEIVE / SEND)
    counterparty:       Optional[str]                = None
    counterparty_label: Optional[str]                = None
    counterparty_score: Optional[TraceabilityResult] = None

    # SWAP-specific
    dex_name: Optional[str]       = None
    hops:     Optional[list[str]] = None  # intermediate assets in multi-hop

    # LIQUIDITY-specific
    lp_action:  Optional[str] = None  # 'add' | 'remove'
    pool_label: Optional[str] = None

    # BTC change detection flag
    has_change_output: bool = False

    # Optional USD total (sum of absolute flow values)
    usd_total: Optional[Decimal] = None

    raw_transfers: list[TokenTransfer] = field(default_factory=list)


@dataclass
class TimelineEvent:
    """Deduplicated event for session timeline view."""
    timestamp:    datetime
    chain:        Chain
    tx_hash:      str
    kind:         TxType
    address:      str             # which session address this primarily belongs to
    address_label: Optional[str]
    net_flows:    dict[str, Decimal]
    counterparty: Optional[str]
    counterparty_label: Optional[str]
    is_internal:  bool            = False  # both sides are in-scope session addresses
    usd_total:    Optional[Decimal] = None
