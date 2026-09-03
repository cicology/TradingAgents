"""TA-003: the risk agent's max_size_pct must be the tightest cap that
ultimately wins, regardless of what Kelly sizing would otherwise allow."""

from __future__ import annotations

from trading_desk.config import KELLY_CAP
from trading_desk.pipeline import _normalize_decision


def proposal(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "action": "BUY",
        "verdict": "APPROVE",
        "confidence": 80,
        "entry": 100.0,
        "stop": 95.0,
        "targets": [110.0],
        "max_size_pct": 1.0,
        "rationale": "fixture",
        "risks": [],
    }
    value.update(overrides)
    return value


def test_risk_maximum_caps_computed_size() -> None:
    decision = _normalize_decision(proposal(max_size_pct=1.0))

    assert decision["size_pct"] <= 1.0
    assert decision["max_size_pct"] <= 1.0


def test_zero_risk_maximum_rejects_directional_trade() -> None:
    decision = _normalize_decision(proposal(max_size_pct=0))

    assert decision["verdict"] == "REJECT"
    assert decision["size_pct"] == 0.0


def test_declared_cap_above_kelly_cap_is_still_bounded_by_kelly_cap() -> None:
    """A generous risk-agent cap (e.g. 5%) must not let sizing exceed the
    desk's own Kelly hard cap — the tightest of the two always wins."""
    decision = _normalize_decision(proposal(max_size_pct=5.0))

    assert decision["max_size_pct"] <= round(KELLY_CAP * 100.0, 4)


def test_missing_max_size_pct_does_not_default_to_full_kelly_cap() -> None:
    """A proposal that omits max_size_pct entirely (malformed/adversarial
    LLM output) must not be treated as 'no limit requested' and fall back
    to the full Kelly cap — it should size as if the risk agent asked for
    nothing at all."""
    decision = _normalize_decision(proposal(max_size_pct=None))

    assert decision["verdict"] == "REJECT"
    assert decision["size_pct"] == 0.0


def test_negative_max_size_pct_is_treated_as_zero() -> None:
    decision = _normalize_decision(proposal(max_size_pct=-3.0))

    assert decision["verdict"] == "REJECT"
    assert decision["size_pct"] == 0.0
