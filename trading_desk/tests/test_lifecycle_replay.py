"""TA-204: position lifecycle replay determines stop/target/expiry
outcome from subsequent bars, resolving conservatively when a single bar's
range could contain both stop and target (worst case first, never
optimistic)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from trading_desk.domain import Action, ExecutionStatus, OrderIntent, PaperExecution, ValidationError
from trading_desk.lifecycle import replay_position
from trading_desk.market_data import Bar

BASE = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)


def _bar(hours: int, *, o: float, h: float, l: float, c: float) -> Bar:
    return Bar(time=BASE + timedelta(hours=hours), open=o, high=h, low=l, close=c, volume=100)


def buy_intent(stop=2475.0, target=2550.0, quantity=4.0) -> OrderIntent:
    return OrderIntent(
        venue="mt5", symbol="XAUUSD", action=Action.BUY, quantity=quantity,
        stop=stop, target=target, strategy_version="xau-ema-crossover@1", decision_id="dec-1",
    )


def sell_intent(stop=2525.0, target=2450.0, quantity=4.0) -> OrderIntent:
    return OrderIntent(
        venue="mt5", symbol="XAUUSD", action=Action.SELL, quantity=quantity,
        stop=stop, target=target, strategy_version="xau-ema-crossover@1", decision_id="dec-1",
    )


def entry_execution(intent: OrderIntent, fill_price: float = 2500.0) -> PaperExecution:
    return PaperExecution(
        order_intent=intent, status=ExecutionStatus.PAPER, fill_price=fill_price,
        reason="fixture", executed_at=BASE,
    )


def test_buy_stop_hit_closes_at_stop_price() -> None:
    intent = buy_intent()
    bars = [_bar(1, o=2495, h=2498, l=2470, c=2472)]  # low breaches stop
    outcome, reason = replay_position(
        intent, entry_execution(intent), bars, equity=10_000.0, commission_per_unit=0.0, max_holding_bars=10,
    )
    assert reason == "stop_hit"
    assert outcome.realized_pnl_pct == pytest.approx(-1.0)  # risked exactly 1% by construction


def test_buy_target_hit_closes_at_target_price() -> None:
    intent = buy_intent()
    bars = [_bar(1, o=2510, h=2555, l=2505, c=2552)]
    outcome, reason = replay_position(
        intent, entry_execution(intent), bars, equity=10_000.0, commission_per_unit=0.0, max_holding_bars=10,
    )
    assert reason == "target_hit"
    assert outcome.realized_pnl_pct > 0


def test_buy_bar_touching_both_levels_resolves_conservatively_to_stop() -> None:
    """A single bar whose range spans both the stop and the target is
    exactly the case where intrabar path is unknown — resolve to the
    worse outcome (stop), never assume the favorable order happened."""
    intent = buy_intent()
    bars = [_bar(1, o=2500, h=2560, l=2470, c=2555)]  # both stop and target inside this bar's range
    outcome, reason = replay_position(
        intent, entry_execution(intent), bars, equity=10_000.0, commission_per_unit=0.0, max_holding_bars=10,
    )
    assert reason == "stop_hit"
    assert outcome.realized_pnl_pct < 0


def test_sell_stop_hit_closes_at_stop_price() -> None:
    intent = sell_intent()
    bars = [_bar(1, o=2505, h=2530, l=2500, c=2528)]  # high breaches stop
    outcome, reason = replay_position(
        intent, entry_execution(intent, fill_price=2500.0), bars,
        equity=10_000.0, commission_per_unit=0.0, max_holding_bars=10,
    )
    assert reason == "stop_hit"
    assert outcome.realized_pnl_pct < 0


def test_neither_level_hit_within_bars_expires_at_last_close() -> None:
    intent = buy_intent()
    bars = [
        _bar(1, o=2500, h=2510, l=2495, c=2505),
        _bar(2, o=2505, h=2512, l=2498, c=2508),
    ]
    outcome, reason = replay_position(
        intent, entry_execution(intent), bars, equity=10_000.0, commission_per_unit=0.0, max_holding_bars=10,
    )
    assert reason == "expiry"
    assert outcome.closed_at == bars[-1].time


def test_max_holding_bars_forces_expiry_even_if_more_bars_exist() -> None:
    intent = buy_intent()
    bars = [
        _bar(1, o=2500, h=2510, l=2495, c=2505),
        _bar(2, o=2505, h=2512, l=2498, c=2508),
        _bar(3, o=2508, h=2600, l=2400, c=2550),  # would hit target/stop, but past the holding limit
    ]
    outcome, reason = replay_position(
        intent, entry_execution(intent), bars, equity=10_000.0, commission_per_unit=0.0, max_holding_bars=2,
    )
    assert reason == "expiry"
    assert outcome.closed_at == bars[1].time


def test_commission_reduces_realized_pnl() -> None:
    intent = buy_intent()
    bars = [_bar(1, o=2510, h=2555, l=2505, c=2552)]
    no_commission, _ = replay_position(
        intent, entry_execution(intent), bars, equity=10_000.0, commission_per_unit=0.0, max_holding_bars=10,
    )
    with_commission, _ = replay_position(
        intent, entry_execution(intent), bars, equity=10_000.0, commission_per_unit=1.0, max_holding_bars=10,
    )
    assert with_commission.realized_pnl_pct < no_commission.realized_pnl_pct


def test_no_subsequent_bars_is_rejected() -> None:
    intent = buy_intent()
    with pytest.raises(ValidationError, match="at least one"):
        replay_position(
            intent, entry_execution(intent), [], equity=10_000.0, commission_per_unit=0.0, max_holding_bars=10,
        )


def test_missing_stop_is_rejected() -> None:
    intent = buy_intent(stop=None)
    bars = [_bar(1, o=2500, h=2510, l=2495, c=2505)]
    with pytest.raises(ValidationError, match="stop"):
        replay_position(
            intent, entry_execution(intent), bars, equity=10_000.0, commission_per_unit=0.0, max_holding_bars=10,
        )


def test_replay_is_deterministic() -> None:
    intent = buy_intent()
    bars = [_bar(1, o=2510, h=2555, l=2505, c=2552)]
    first = replay_position(
        intent, entry_execution(intent), bars, equity=10_000.0, commission_per_unit=0.0, max_holding_bars=10,
    )
    second = replay_position(
        intent, entry_execution(intent), bars, equity=10_000.0, commission_per_unit=0.0, max_holding_bars=10,
    )
    assert first == second
