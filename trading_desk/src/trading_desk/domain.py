"""Canonical domain models for the desk (TA-101).

Every model validates itself in `__post_init__`: a constructed instance is
guaranteed valid, and an invalid one never exists — callers get a
`ValidationError` instead of a half-formed object. This is the fail-closed
contract Phase 1's ledger and validator (TA-102, TA-103) build on: nothing
downstream should re-check invariants these constructors already enforce.

Models are intentionally plain, frozen dataclasses — no ORM, no premature
PostgreSQL-shaped abstraction. `trading_desk.ledger` (TA-102) is the only
thing that knows how to persist them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ValidationError(ValueError):
    """A domain model or decision failed validation. Callers must treat
    this as a fail-closed rejection, not something to retry as-is."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


class Action(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class Verdict(str, Enum):
    APPROVE = "APPROVE"
    REDUCE = "REDUCE"
    REJECT = "REJECT"


class LifecycleEventType(str, Enum):
    OPEN = "open"
    UPDATE = "update"
    PARTIAL_CLOSE = "partial_close"
    CLOSE = "close"
    CANCEL = "cancel"
    REJECT = "reject"
    RECONCILE = "reconcile"


class ExecutionStatus(str, Enum):
    PAPER = "paper"
    SKIPPED = "skipped"
    BLOCKED = "blocked"
    REJECTED = "rejected"
    SUBMITTED = "submitted"


@dataclass(frozen=True)
class MarketSnapshot:
    instrument: str
    as_of: datetime
    bid: float | None = None
    ask: float | None = None
    last_close: float | None = None
    source: str = "unknown"

    def __post_init__(self) -> None:
        _require(bool(self.instrument), "instrument is required")
        _require(self.as_of.tzinfo is not None, "as_of must be timezone-aware")
        if self.bid is not None and self.ask is not None:
            _require(self.ask >= self.bid, "ask must be >= bid")

    def spread(self) -> float | None:
        if self.bid is None or self.ask is None:
            return None
        return self.ask - self.bid

    def age_seconds(self, *, now: datetime) -> float:
        return (now - self.as_of).total_seconds()


@dataclass(frozen=True)
class Evidence:
    market: MarketSnapshot
    technical: dict[str, Any] = field(default_factory=dict)
    news_macro: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TradeDecision:
    """A canonical, validated trade decision — the output of TA-103's
    validator, never raw LLM JSON. A rejected decision (verdict=REJECT) is
    a valid, constructable TradeDecision, not an exception; only a
    malformed one (e.g. REJECT carrying nonzero size, or a directional
    action missing its stop) fails to construct."""

    instrument: str
    strategy_version: str
    action: Action
    verdict: Verdict
    size_pct: float
    entry: float | None
    stop: float | None
    targets: tuple[float, ...]
    rationale: str
    model: str | None
    generated_at: datetime

    def __post_init__(self) -> None:
        _require(bool(self.instrument), "instrument is required")
        _require(bool(self.strategy_version), "strategy_version is required")
        _require(self.size_pct >= 0, "size_pct must be non-negative")
        if self.verdict == Verdict.REJECT:
            _require(self.size_pct == 0, "REJECT verdict must carry zero size")
        if self.action in (Action.BUY, Action.SELL) and self.verdict != Verdict.REJECT:
            _require(self.entry is not None, "directional decision requires entry")
            _require(self.stop is not None, "directional decision requires stop")


@dataclass(frozen=True)
class OrderIntent:
    """What the desk intends to submit to a venue — already sized and
    stopped by deterministic code, never a raw LLM proposal."""

    venue: str
    symbol: str
    action: Action
    quantity: float
    stop: float | None
    target: float | None
    strategy_version: str
    decision_id: str

    def __post_init__(self) -> None:
        _require(bool(self.venue), "venue is required")
        _require(bool(self.symbol), "symbol is required")
        _require(self.action in (Action.BUY, Action.SELL), "OrderIntent action must be BUY or SELL")
        _require(self.quantity > 0, "quantity must be positive")
        _require(bool(self.decision_id), "decision_id is required for traceability")


@dataclass(frozen=True)
class PaperExecution:
    order_intent: OrderIntent
    status: ExecutionStatus
    fill_price: float | None
    reason: str | None
    executed_at: datetime


@dataclass(frozen=True)
class LifecycleEvent:
    """An immutable fact about a position's life. The ledger (TA-102)
    stores these append-only, keyed by `event_id` for idempotent writes."""

    event_id: str
    venue: str
    symbol: str
    event_type: LifecycleEventType
    occurred_at: datetime
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require(bool(self.event_id), "event_id is required")
        _require(bool(self.venue), "venue is required")
        _require(bool(self.symbol), "symbol is required")


@dataclass(frozen=True)
class Outcome:
    venue: str
    symbol: str
    strategy_version: str
    opened_at: datetime
    closed_at: datetime
    realized_pnl_pct: float

    def __post_init__(self) -> None:
        _require(bool(self.venue), "venue is required")
        _require(bool(self.symbol), "symbol is required")
        _require(self.closed_at >= self.opened_at, "closed_at must not precede opened_at")


@dataclass(frozen=True)
class StrategyVersion:
    name: str
    version: str
    horizon: str

    def __post_init__(self) -> None:
        _require(bool(self.name), "name is required")
        _require(bool(self.version), "version is required")

    def id(self) -> str:
        return f"{self.name}@{self.version}"


@dataclass(frozen=True)
class EvaluationRun:
    """Minimal placeholder for Phase 3's evaluation/promotion framework —
    just enough identity to reference from a ledger event now, without
    pulling forward backtest/walk-forward mechanics that belong there."""

    strategy_version: str
    started_at: datetime
    status: str = "pending"

    def __post_init__(self) -> None:
        _require(bool(self.strategy_version), "strategy_version is required")
