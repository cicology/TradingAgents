"""Characterization tests for current desk behavior, captured before Phase 0
safety refactors change it. These pin down what the system does today so
later fixes are provably intentional changes, not silent regressions.
"""

from __future__ import annotations

from trading_desk.agents import heuristic_decision
from trading_desk.mt5_config import live_orders_allowed
from trading_desk.pipeline import _normalize_decision


def test_dry_run_is_rejected_and_zero_sized(market_snapshot) -> None:
    decision = _normalize_decision(heuristic_decision(market_snapshot))

    assert decision["action"] == "BUY"
    assert decision["verdict"] == "REJECT"
    assert decision["size_pct"] == 0.0


def test_live_orders_are_disallowed_by_default(monkeypatch) -> None:
    monkeypatch.delenv("DESK_ALLOW_LIVE_ORDERS", raising=False)

    assert live_orders_allowed() is False
