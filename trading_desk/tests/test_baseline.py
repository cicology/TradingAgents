"""TA-302: the deterministic non-AI baseline.

A strategy that cannot beat buy-and-hold on the same bars, under the same
transaction costs, has not demonstrated an edge. The baseline is versioned
and reproducible so a promotion report can name exactly which baseline a
candidate was compared against.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from trading_desk.baseline import BASELINE_VERSION, buy_and_hold_outcome, compare_to_baseline
from trading_desk.market_data import Bar

BASE = datetime(2026, 9, 3, 0, 0, tzinfo=timezone.utc)


def _bars(closes: list[float]) -> list[Bar]:
    return [
        Bar(time=BASE + timedelta(hours=i), open=c, high=c + 1.0, low=c - 1.0, close=c, volume=100)
        for i, c in enumerate(closes)
    ]


def test_baseline_version_is_stable_and_named() -> None:
    assert BASELINE_VERSION == "buy-and-hold@1"


def test_rising_series_produces_a_positive_baseline_return() -> None:
    # Enter at first open 100, exit at last close 110, quantity sized so
    # that a 1-unit move is 1% of equity: equity 1000, quantity 10.
    outcome = buy_and_hold_outcome(
        _bars([100.0, 105.0, 110.0]),
        instrument="gold", venue="mt5", symbol="XAUUSD",
        equity=1000.0, quantity=10.0, spread=0.0, slippage=0.0, commission_per_unit=0.0,
    )
    # (110 - 100) * 10 = 100 profit on 1000 equity = 10%
    assert outcome.realized_pnl_pct == pytest.approx(10.0)
    assert outcome.strategy_version == BASELINE_VERSION


def test_falling_series_produces_a_negative_baseline_return() -> None:
    outcome = buy_and_hold_outcome(
        _bars([110.0, 105.0, 100.0]),
        instrument="gold", venue="mt5", symbol="XAUUSD",
        equity=1000.0, quantity=10.0, spread=0.0, slippage=0.0, commission_per_unit=0.0,
    )
    assert outcome.realized_pnl_pct == pytest.approx(-10.0)


def test_baseline_pays_the_same_transaction_costs_as_the_strategy() -> None:
    """A costless baseline would be an unfairly easy target. The baseline
    pays the same spread, slippage, and (round-trip) commission."""
    free = buy_and_hold_outcome(
        _bars([100.0, 110.0]),
        instrument="gold", venue="mt5", symbol="XAUUSD",
        equity=1000.0, quantity=10.0, spread=0.0, slippage=0.0, commission_per_unit=0.0,
    )
    costed = buy_and_hold_outcome(
        _bars([100.0, 110.0]),
        instrument="gold", venue="mt5", symbol="XAUUSD",
        equity=1000.0, quantity=10.0, spread=0.4, slippage=0.1, commission_per_unit=0.05,
    )
    assert costed.realized_pnl_pct < free.realized_pnl_pct


def test_baseline_is_reproducible() -> None:
    bars = _bars([100.0, 105.0, 110.0])
    kwargs = dict(
        instrument="gold", venue="mt5", symbol="XAUUSD",
        equity=1000.0, quantity=10.0, spread=0.3, slippage=0.1, commission_per_unit=0.02,
    )
    assert buy_and_hold_outcome(bars, **kwargs) == buy_and_hold_outcome(bars, **kwargs)


def test_baseline_spans_the_full_window() -> None:
    bars = _bars([100.0, 105.0, 110.0])
    outcome = buy_and_hold_outcome(
        bars, instrument="gold", venue="mt5", symbol="XAUUSD",
        equity=1000.0, quantity=10.0, spread=0.0, slippage=0.0, commission_per_unit=0.0,
    )
    assert outcome.opened_at == bars[0].time
    assert outcome.closed_at == bars[-1].time


def test_fewer_than_two_bars_has_no_baseline() -> None:
    assert buy_and_hold_outcome(
        _bars([100.0]), instrument="gold", venue="mt5", symbol="XAUUSD",
        equity=1000.0, quantity=10.0, spread=0.0, slippage=0.0, commission_per_unit=0.0,
    ) is None
    assert buy_and_hold_outcome(
        [], instrument="gold", venue="mt5", symbol="XAUUSD",
        equity=1000.0, quantity=10.0, spread=0.0, slippage=0.0, commission_per_unit=0.0,
    ) is None


def test_comparison_reports_deltas_and_whether_the_strategy_beat_the_baseline() -> None:
    strategy = {"total_return_pct": 5.0, "max_drawdown_pct": 2.0}
    baseline = {"total_return_pct": 3.0, "max_drawdown_pct": 4.0}
    comparison = compare_to_baseline(strategy, baseline)

    assert comparison["baseline_version"] == BASELINE_VERSION
    assert comparison["return_delta_pct"] == pytest.approx(2.0)
    assert comparison["drawdown_delta_pct"] == pytest.approx(-2.0)  # strategy drew down less
    assert comparison["beats_baseline_return"] is True
    assert comparison["beats_baseline_drawdown"] is True


def test_comparison_marks_a_strategy_that_loses_to_the_baseline() -> None:
    strategy = {"total_return_pct": 1.0, "max_drawdown_pct": 6.0}
    baseline = {"total_return_pct": 3.0, "max_drawdown_pct": 4.0}
    comparison = compare_to_baseline(strategy, baseline)

    assert comparison["beats_baseline_return"] is False
    assert comparison["beats_baseline_drawdown"] is False


def test_comparison_with_no_baseline_is_explicit_not_a_silent_pass() -> None:
    """No baseline means 'not compared', which must never read as 'passed'."""
    comparison = compare_to_baseline({"total_return_pct": 5.0, "max_drawdown_pct": 1.0}, None)
    assert comparison["beats_baseline_return"] is None
    assert comparison["beats_baseline_drawdown"] is None
