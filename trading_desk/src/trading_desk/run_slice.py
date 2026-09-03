"""TA-206: XAU/USD vertical-slice orchestrator.

Ties TA-201-205 into one reproducible run:

    market data -> evidence hash -> deterministic strategy -> validation
    -> sizing -> paper order -> fill simulation -> lifecycle replay ->
    ledger persistence

Every run is described by an explicit `RunConfig`, so results are
reproducible from config + bars alone (see `evidence.compute_evidence_hash`).
This function is entirely deterministic and offline given `bars` and
`subsequent_bars` — a caller (CLI, scheduler) is responsible for fetching
those via `market_data.fetch_closed_bars()` from a live MT5 connection.

Failure modes that are expected in normal operation (no data, stale data,
insufficient history, a rejected decision, an unsizeable order) are
returned as a `RunResult` with an explanatory `reason`, never raised —
this is what lets a caller implement retry/backoff policy around a
transient condition (e.g. stale data because the feed lagged) without
having to parse exception types. A genuine bug (e.g. a domain
`ValidationError` from malformed internal state) still propagates.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from trading_desk import ledger
from trading_desk.domain import LifecycleEvent, LifecycleEventType, MarketSnapshot, ValidationError, Verdict
from trading_desk.evidence import compute_evidence_hash
from trading_desk.lifecycle import replay_position
from trading_desk.market_data import Bar, is_fresh
from trading_desk.paper_broker import build_order_intent, simulate_fill
from trading_desk.sizing import size_decision
from trading_desk.strategy import ema_crossover_proposal
from trading_desk.validation import validate_decision


@dataclass(frozen=True)
class RunConfig:
    instrument: str
    venue_symbol: str
    strategy_version: str
    horizon: str
    equity: float
    base_risk_pct: float
    spread: float
    slippage: float
    commission_per_unit: float
    max_holding_bars: int
    venue: str = "mt5"


@dataclass(frozen=True)
class RunResult:
    status: str  # "rejected" | "no_trade" | "opened" | "closed"
    reason: str
    evidence_hash: str | None = None
    decision_id: str | None = None
    outcome_id: str | None = None


def run_slice(
    conn: sqlite3.Connection,
    bars: list[Bar],
    subsequent_bars: list[Bar],
    config: RunConfig,
    *,
    now: datetime,
) -> RunResult:
    if not bars:
        return RunResult(status="rejected", reason="no market data")

    last_bar = bars[-1]
    if not is_fresh(last_bar, horizon=config.horizon, now=now):
        return RunResult(status="rejected", reason=f"stale market data: last bar at {last_bar.time.isoformat()}")

    evidence_hash = compute_evidence_hash(bars, instrument=config.instrument, horizon=config.horizon)
    proposal = ema_crossover_proposal(bars, strategy_version=config.strategy_version)
    market = MarketSnapshot(instrument=config.instrument, as_of=last_bar.time, last_close=last_bar.close)

    try:
        decision = validate_decision(
            proposal,
            instrument=config.instrument,
            strategy_version=config.strategy_version,
            market=market,
            horizon=config.horizon,
            now=now,
        )
    except ValidationError as exc:
        return RunResult(status="rejected", reason=f"decision validation failed: {exc}", evidence_hash=evidence_hash)

    sized = size_decision(decision, base_risk_pct=config.base_risk_pct)

    # decision_id is derived from the evidence hash + strategy version, not
    # a random UUID: replaying the same bars produces the same decision_id,
    # so record_decision()'s idempotency (TA-106) makes a repeated run a
    # no-op rather than a duplicate ledger row.
    decision_id = f"{evidence_hash}:{config.strategy_version}"
    ledger.record_decision(conn, decision_id, sized)

    if sized.verdict == Verdict.REJECT or sized.size_pct <= 0:
        return RunResult(
            status="no_trade",
            reason="strategy produced no trade or sizing reduced it to zero",
            evidence_hash=evidence_hash,
            decision_id=decision_id,
        )

    try:
        order_intent = build_order_intent(
            sized, venue=config.venue, symbol=config.venue_symbol, equity=config.equity, decision_id=decision_id
        )
    except ValidationError as exc:
        return RunResult(
            status="rejected", reason=f"order sizing failed: {exc}", evidence_hash=evidence_hash, decision_id=decision_id
        )

    if not subsequent_bars:
        return RunResult(
            status="opened",
            reason="decision sized and recorded; no subsequent bars yet to simulate a fill",
            evidence_hash=evidence_hash,
            decision_id=decision_id,
        )

    entry_execution = simulate_fill(
        order_intent,
        subsequent_bars[0],
        spread=config.spread,
        slippage=config.slippage,
        commission_per_unit=config.commission_per_unit,
    )

    ledger.record_lifecycle_event(
        conn,
        _lifecycle_event(
            f"{decision_id}:open",
            config.venue,
            config.venue_symbol,
            LifecycleEventType.OPEN,
            entry_execution.executed_at,
            {"side": order_intent.action.value, "size_pct": sized.size_pct, "quantity": order_intent.quantity},
        ),
    )

    replay = replay_position(
        order_intent,
        entry_execution,
        subsequent_bars,
        equity=config.equity,
        commission_per_unit=config.commission_per_unit,
        max_holding_bars=config.max_holding_bars,
    )

    outcome_id = f"{decision_id}:outcome"
    ledger.record_outcome(conn, outcome_id, replay.outcome)
    ledger.record_lifecycle_event(
        conn,
        _lifecycle_event(
            f"{decision_id}:close",
            config.venue,
            config.venue_symbol,
            LifecycleEventType.CLOSE,
            replay.outcome.closed_at,
            {"realized_pnl_pct": replay.outcome.realized_pnl_pct, "exit_reason": replay.exit_reason},
        ),
    )

    return RunResult(
        status="closed",
        reason=replay.exit_reason,
        evidence_hash=evidence_hash,
        decision_id=decision_id,
        outcome_id=outcome_id,
    )


def _lifecycle_event(event_id, venue, symbol, event_type, occurred_at, payload):
    return LifecycleEvent(
        event_id=event_id, venue=venue, symbol=symbol, event_type=event_type, occurred_at=occurred_at, payload=payload
    )
