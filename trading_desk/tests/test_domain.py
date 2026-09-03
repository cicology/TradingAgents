"""TA-101: canonical domain models validate themselves on construction and
fail closed on malformed input — a model instance is either valid or it
does not exist."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from trading_desk.domain import (
    Action,
    ExecutionStatus,
    LifecycleEvent,
    LifecycleEventType,
    MarketSnapshot,
    OrderIntent,
    Outcome,
    StrategyVersion,
    TradeDecision,
    ValidationError,
    Verdict,
)

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)


def test_market_snapshot_requires_timezone_aware_timestamp() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        MarketSnapshot(instrument="gold", as_of=datetime(2026, 9, 3, 12, 0), last_close=2500.0)


def test_market_snapshot_rejects_inverted_bid_ask() -> None:
    with pytest.raises(ValidationError, match="ask must be"):
        MarketSnapshot(instrument="gold", as_of=NOW, bid=2500.0, ask=2490.0)


def test_market_snapshot_spread_and_age() -> None:
    snap = MarketSnapshot(instrument="gold", as_of=NOW, bid=2499.9, ask=2500.1)
    assert snap.spread() == pytest.approx(0.2)
    assert snap.age_seconds(now=NOW + timedelta(seconds=30)) == pytest.approx(30.0)


def test_trade_decision_reject_must_carry_zero_size() -> None:
    with pytest.raises(ValidationError, match="zero size"):
        TradeDecision(
            instrument="gold",
            strategy_version="xau-swing@1",
            action=Action.BUY,
            verdict=Verdict.REJECT,
            size_pct=1.0,
            entry=2500.0,
            stop=2475.0,
            targets=(2550.0,),
            rationale="fixture",
            model=None,
            generated_at=NOW,
        )


def test_trade_decision_directional_requires_entry_and_stop() -> None:
    with pytest.raises(ValidationError, match="requires stop"):
        TradeDecision(
            instrument="gold",
            strategy_version="xau-swing@1",
            action=Action.BUY,
            verdict=Verdict.APPROVE,
            size_pct=1.0,
            entry=2500.0,
            stop=None,
            targets=(),
            rationale="fixture",
            model=None,
            generated_at=NOW,
        )


def test_trade_decision_hold_needs_no_levels() -> None:
    decision = TradeDecision(
        instrument="gold",
        strategy_version="xau-swing@1",
        action=Action.HOLD,
        verdict=Verdict.REJECT,
        size_pct=0.0,
        entry=None,
        stop=None,
        targets=(),
        rationale="fixture",
        model=None,
        generated_at=NOW,
    )
    assert decision.action is Action.HOLD


def test_order_intent_requires_positive_quantity() -> None:
    with pytest.raises(ValidationError, match="quantity must be positive"):
        OrderIntent(
            venue="mt5",
            symbol="XAUUSD",
            action=Action.BUY,
            quantity=0.0,
            stop=2475.0,
            target=2550.0,
            strategy_version="xau-swing@1",
            decision_id="dec-1",
        )


def test_order_intent_rejects_hold_action() -> None:
    with pytest.raises(ValidationError, match="BUY or SELL"):
        OrderIntent(
            venue="mt5",
            symbol="XAUUSD",
            action=Action.HOLD,
            quantity=0.01,
            stop=2475.0,
            target=2550.0,
            strategy_version="xau-swing@1",
            decision_id="dec-1",
        )


def test_lifecycle_event_requires_identity_fields() -> None:
    with pytest.raises(ValidationError, match="event_id"):
        LifecycleEvent(
            event_id="",
            venue="mt5",
            symbol="XAUUSD",
            event_type=LifecycleEventType.OPEN,
            occurred_at=NOW,
        )


def test_outcome_rejects_closed_before_opened() -> None:
    with pytest.raises(ValidationError, match="closed_at must not precede"):
        Outcome(
            venue="mt5",
            symbol="XAUUSD",
            strategy_version="xau-swing@1",
            opened_at=NOW,
            closed_at=NOW - timedelta(hours=1),
            realized_pnl_pct=-0.4,
        )


def test_strategy_version_id_composes_name_and_version() -> None:
    version = StrategyVersion(name="xau-swing", version="1", horizon="1h")
    assert version.id() == "xau-swing@1"


def test_execution_status_enum_values_are_lowercase() -> None:
    assert ExecutionStatus.PAPER.value == "paper"
    assert ExecutionStatus.REJECTED.value == "rejected"
