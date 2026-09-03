"""TA-203: the paper order/fill simulator turns a sized TradeDecision into
an OrderIntent (quantity derived from risk, never a guess) and then a
PaperExecution with explicit spread, slippage, and commission assumptions
— never a costless fantasy fill."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from trading_desk.domain import Action, ExecutionStatus, TradeDecision, ValidationError, Verdict
from trading_desk.market_data import Bar
from trading_desk.paper_broker import build_order_intent, simulate_fill

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)


def approved_buy(**overrides) -> TradeDecision:
    fields = dict(
        instrument="gold",
        strategy_version="xau-ema-crossover@1",
        action=Action.BUY,
        verdict=Verdict.APPROVE,
        size_pct=1.0,
        entry=2500.0,
        stop=2475.0,
        targets=(2550.0,),
        rationale="fixture",
        model=None,
        generated_at=NOW,
    )
    fields.update(overrides)
    return TradeDecision(**fields)


def bar(open_=2501.0) -> Bar:
    return Bar(time=NOW, open=open_, high=open_ + 5, low=open_ - 5, close=open_ + 1, volume=100)


def test_build_order_intent_sizes_quantity_from_risk() -> None:
    intent = build_order_intent(approved_buy(), venue="mt5", symbol="XAUUSD", equity=10_000.0, decision_id="dec-1")
    # risk_money = 10000 * 1% = 100; stop_distance = 2500 - 2475 = 25; quantity = 100 / 25 = 4
    assert intent.quantity == pytest.approx(4.0)
    assert intent.action is Action.BUY
    assert intent.decision_id == "dec-1"


def test_build_order_intent_rejects_hold_decision() -> None:
    hold = approved_buy(action=Action.HOLD, verdict=Verdict.REJECT, size_pct=0.0, entry=None, stop=None, targets=())
    with pytest.raises(ValidationError, match="directional"):
        build_order_intent(hold, venue="mt5", symbol="XAUUSD", equity=10_000.0, decision_id="dec-1")


def test_build_order_intent_rejects_zero_size() -> None:
    zero = approved_buy(size_pct=0.0)
    with pytest.raises(ValidationError, match="quantity must be positive"):
        build_order_intent(zero, venue="mt5", symbol="XAUUSD", equity=10_000.0, decision_id="dec-1")


def test_buy_fill_price_includes_spread_and_slippage() -> None:
    intent = build_order_intent(approved_buy(), venue="mt5", symbol="XAUUSD", equity=10_000.0, decision_id="dec-1")
    execution = simulate_fill(intent, bar(open_=2501.0), spread=0.30, slippage=0.10, commission_per_unit=0.02)

    # BUY pays the spread and slippage against it: open + half-spread + slippage
    assert execution.fill_price == pytest.approx(2501.0 + 0.15 + 0.10)
    assert execution.status is ExecutionStatus.PAPER


def test_sell_fill_price_includes_spread_and_slippage() -> None:
    sell = approved_buy(action=Action.SELL, entry=2500.0, stop=2525.0, targets=(2450.0,))
    intent = build_order_intent(sell, venue="mt5", symbol="XAUUSD", equity=10_000.0, decision_id="dec-1")
    execution = simulate_fill(intent, bar(open_=2501.0), spread=0.30, slippage=0.10, commission_per_unit=0.02)

    # SELL also pays the spread and slippage against it: open - half-spread - slippage
    assert execution.fill_price == pytest.approx(2501.0 - 0.15 - 0.10)


def test_commission_and_costs_are_recorded_in_the_execution_reason() -> None:
    intent = build_order_intent(approved_buy(), venue="mt5", symbol="XAUUSD", equity=10_000.0, decision_id="dec-1")
    execution = simulate_fill(intent, bar(), spread=0.30, slippage=0.10, commission_per_unit=0.02)

    assert "spread=0.3" in execution.reason
    assert "slippage=0.1" in execution.reason
    assert "commission_per_unit=0.02" in execution.reason


def test_execution_timestamp_is_the_fill_bar_time_not_wall_clock() -> None:
    """This is a deterministic bar-replay system: a fill's timestamp must
    come from the bar it filled on, not datetime.now() — otherwise
    replaying historical bars produces an Outcome whose opened_at is
    'whenever the simulation ran' rather than the bar's actual time,
    which can even fail Outcome's own closed_at >= opened_at check when
    replaying old data."""
    intent = build_order_intent(approved_buy(), venue="mt5", symbol="XAUUSD", equity=10_000.0, decision_id="dec-1")
    fill_bar = bar()
    execution = simulate_fill(intent, fill_bar, spread=0.30, slippage=0.10, commission_per_unit=0.02)
    assert execution.executed_at == fill_bar.time


def test_fill_is_deterministic_across_repeated_calls() -> None:
    intent = build_order_intent(approved_buy(), venue="mt5", symbol="XAUUSD", equity=10_000.0, decision_id="dec-1")
    first = simulate_fill(intent, bar(), spread=0.30, slippage=0.10, commission_per_unit=0.02)
    second = simulate_fill(intent, bar(), spread=0.30, slippage=0.10, commission_per_unit=0.02)
    assert first.fill_price == second.fill_price
