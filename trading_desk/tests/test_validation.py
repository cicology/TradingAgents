"""TA-103: the strict decision validator turns a raw LLM/agent proposal
dict into a canonical TradeDecision, or fails closed. It never returns a
best-effort guess for unknown, incomplete, contradictory, stale, or
unsupported input."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from trading_desk.domain import Action, MarketSnapshot, ValidationError, Verdict
from trading_desk.validation import validate_decision

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)


def snapshot(**overrides) -> MarketSnapshot:
    fields = {
        "instrument": "gold",
        "as_of": NOW,
        "bid": 2499.9,
        "ask": 2500.1,
        "last_close": 2500.0,
    }
    fields.update(overrides)
    return MarketSnapshot(**fields)


def proposal(**overrides) -> dict:
    fields = {
        "action": "BUY",
        "verdict": "APPROVE",
        "entry": 2500.0,
        "stop": 2475.0,
        "targets": [2550.0],
        "rationale": "fixture",
    }
    fields.update(overrides)
    return fields


def test_unsupported_action_is_rejected() -> None:
    with pytest.raises(ValidationError, match="unsupported action"):
        validate_decision(
            proposal(action="SHORT"), instrument="gold", strategy_version="xau-swing@1",
            market=snapshot(), now=NOW,
        )


def test_unsupported_verdict_is_rejected() -> None:
    with pytest.raises(ValidationError, match="unsupported verdict"):
        validate_decision(
            proposal(verdict="MAYBE"), instrument="gold", strategy_version="xau-swing@1",
            market=snapshot(), now=NOW,
        )


def test_stale_snapshot_is_rejected_for_intraday_horizon() -> None:
    stale_market = snapshot(as_of=NOW - timedelta(minutes=10))
    with pytest.raises(ValidationError, match="stale"):
        validate_decision(
            proposal(), instrument="gold", strategy_version="xau-15m@1",
            market=stale_market, horizon="15m", now=NOW,
        )


def test_snapshot_within_freshness_window_is_accepted() -> None:
    fresh_market = snapshot(as_of=NOW - timedelta(minutes=2))
    decision = validate_decision(
        proposal(), instrument="gold", strategy_version="xau-15m@1",
        market=fresh_market, horizon="15m", now=NOW,
    )
    assert decision.action is Action.BUY


def test_absurdly_wide_spread_is_rejected() -> None:
    bad_market = snapshot(bid=2400.0, ask=2600.0)  # ~8% of last_close
    with pytest.raises(ValidationError, match="spread"):
        validate_decision(
            proposal(), instrument="gold", strategy_version="xau-swing@1",
            market=bad_market, now=NOW,
        )


def test_buy_stop_above_entry_is_contradictory() -> None:
    with pytest.raises(ValidationError, match="stop"):
        validate_decision(
            proposal(stop=2525.0), instrument="gold", strategy_version="xau-swing@1",
            market=snapshot(), now=NOW,
        )


def test_sell_stop_below_entry_is_contradictory() -> None:
    with pytest.raises(ValidationError, match="stop"):
        validate_decision(
            proposal(action="SELL", stop=2475.0), instrument="gold", strategy_version="xau-swing@1",
            market=snapshot(), now=NOW,
        )


def test_buy_target_below_entry_is_contradictory() -> None:
    with pytest.raises(ValidationError, match="target"):
        validate_decision(
            proposal(targets=[2490.0]), instrument="gold", strategy_version="xau-swing@1",
            market=snapshot(), now=NOW,
        )


def test_atr_style_stop_distance_is_accepted() -> None:
    decision = validate_decision(
        proposal(stop=25.0), instrument="gold", strategy_version="xau-swing@1",
        market=snapshot(), now=NOW,
    )
    assert decision.stop == 25.0


def test_directional_decision_missing_stop_is_rejected() -> None:
    with pytest.raises(ValidationError, match="stop"):
        validate_decision(
            proposal(stop=None), instrument="gold", strategy_version="xau-swing@1",
            market=snapshot(), now=NOW,
        )


def test_hold_action_passes_through_with_zero_size() -> None:
    decision = validate_decision(
        proposal(action="HOLD", verdict="REDUCE"), instrument="gold", strategy_version="xau-swing@1",
        market=snapshot(), now=NOW,
    )
    assert decision.action is Action.HOLD
    assert decision.size_pct == 0.0


def test_reject_verdict_passes_through_with_zero_size() -> None:
    decision = validate_decision(
        proposal(verdict="REJECT"), instrument="gold", strategy_version="xau-swing@1",
        market=snapshot(), now=NOW,
    )
    assert decision.verdict is Verdict.REJECT
    assert decision.size_pct == 0.0


def test_valid_buy_proposal_produces_unsized_approved_decision() -> None:
    """TA-103 validates structure/direction/freshness — it does not size.
    TA-104 computes size_pct deterministically from this decision."""
    decision = validate_decision(
        proposal(), instrument="gold", strategy_version="xau-swing@1",
        market=snapshot(), now=NOW,
    )
    assert decision.verdict is Verdict.APPROVE
    assert decision.size_pct == 0.0
    assert decision.entry == 2500.0
    assert decision.stop == 2475.0
    assert decision.targets == (2550.0,)
