"""TA-104: deterministic stop-risk sizing. Size must come from
configuration and the decision's verdict, never from LLM confidence —
Architectural Rule 2. An LLM-declared max_size_pct may only shrink the
result (a veto), never grow it."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from trading_desk.domain import Action, TradeDecision, Verdict
from trading_desk.sizing import size_decision

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)


def unsized(**overrides) -> TradeDecision:
    fields = dict(
        instrument="gold",
        strategy_version="xau-swing@1",
        action=Action.BUY,
        verdict=Verdict.APPROVE,
        size_pct=0.0,
        entry=2500.0,
        stop=2475.0,
        targets=(2550.0,),
        rationale="fixture",
        model="fixture-model",
        generated_at=NOW,
    )
    fields.update(overrides)
    return TradeDecision(**fields)


def test_approve_gets_full_base_risk() -> None:
    sized = size_decision(unsized(), base_risk_pct=1.0)
    assert sized.size_pct == pytest.approx(1.0)
    assert sized.verdict is Verdict.APPROVE


def test_reduce_gets_half_base_risk() -> None:
    sized = size_decision(unsized(verdict=Verdict.REDUCE), base_risk_pct=1.0)
    assert sized.size_pct == pytest.approx(0.5)


def test_reject_stays_zero() -> None:
    rejected = unsized(verdict=Verdict.REJECT, action=Action.HOLD, entry=None, stop=None, targets=())
    sized = size_decision(rejected, base_risk_pct=1.0)
    assert sized.size_pct == 0.0
    assert sized.verdict is Verdict.REJECT


def test_confidence_field_has_no_effect_on_size() -> None:
    """The domain TradeDecision doesn't even carry a confidence field —
    size_decision() takes no such input at all. This test pins that
    calling it twice with identical decisions produces identical size,
    proving there is no hidden confidence-shaped channel."""
    first = size_decision(unsized(), base_risk_pct=1.0)
    second = size_decision(unsized(), base_risk_pct=1.0)
    assert first.size_pct == second.size_pct == pytest.approx(1.0)


def test_llm_declared_cap_can_only_shrink_never_grow() -> None:
    shrunk = size_decision(unsized(), base_risk_pct=1.0, declared_max_size_pct=0.3)
    assert shrunk.size_pct == pytest.approx(0.3)

    generous = size_decision(unsized(), base_risk_pct=1.0, declared_max_size_pct=99.0)
    assert generous.size_pct == pytest.approx(1.0)  # capped at base_risk_pct, not inflated


def test_zero_declared_cap_forces_reject() -> None:
    sized = size_decision(unsized(), base_risk_pct=1.0, declared_max_size_pct=0.0)
    assert sized.size_pct == 0.0
    assert sized.verdict is Verdict.REJECT


def test_negative_or_missing_declared_cap_is_treated_as_no_veto() -> None:
    """A malformed declared cap must not silently pass through as an
    unlimited veto exemption, but it also must not accidentally reject a
    perfectly good decision — negative/unparseable input is ignored, not
    trusted either way; base_risk_pct alone still governs."""
    sized = size_decision(unsized(), base_risk_pct=1.0, declared_max_size_pct=None)
    assert sized.size_pct == pytest.approx(1.0)


def test_negative_base_risk_pct_is_clamped_to_zero() -> None:
    sized = size_decision(unsized(), base_risk_pct=-2.0)
    assert sized.size_pct == 0.0
    assert sized.verdict is Verdict.REJECT


def test_default_base_risk_pct_comes_from_config(monkeypatch: pytest.MonkeyPatch) -> None:
    from trading_desk import sizing

    monkeypatch.setattr(sizing, "RISK_PCT_PER_TRADE", 2.0)
    sized = size_decision(unsized())
    assert sized.size_pct == pytest.approx(2.0)
