"""TA-004/TA-005: MT5 stop translation must be direction-aware and reject
what it cannot express; minimum-volume rounding must never increase risk
above what was approved. Fixtures cover XAU/USD (metal) and both FX-major
shapes (5-digit and JPY 3-digit) since broker tick/point conventions
differ across them."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from trading_desk.mt5_broker import _normalize_volume, _stop_distance, place_order
from trading_desk.instruments import UNIVERSE


# ---------------------------------------------------------------------------
# Stop-distance translation
# ---------------------------------------------------------------------------


def test_buy_price_stop_becomes_distance(gold_tick, mt5_info) -> None:
    decision = {"entry": 2500.0, "stop": 2475.0}
    assert _stop_distance(decision, "BUY", gold_tick, mt5_info) == pytest.approx(25.1)


def test_sell_price_stop_becomes_distance(gold_tick, mt5_info) -> None:
    decision = {"entry": 2500.0, "stop": 2525.0}
    assert _stop_distance(decision, "SELL", gold_tick, mt5_info) == pytest.approx(25.1)


def test_atr_distance_is_preserved(gold_tick, mt5_info) -> None:
    decision = {"entry": 2500.0, "stop": 25.0}
    assert _stop_distance(decision, "BUY", gold_tick, mt5_info) == 25.0


def test_buy_stop_on_wrong_side_is_rejected(gold_tick, mt5_info) -> None:
    """A BUY stop placed above the entry/ask is not a valid protective stop."""
    decision = {"entry": 2500.0, "stop": 2525.0}
    assert _stop_distance(decision, "BUY", gold_tick, mt5_info) is None


def test_sell_stop_on_wrong_side_is_rejected(gold_tick, mt5_info) -> None:
    decision = {"entry": 2500.0, "stop": 2475.0}
    assert _stop_distance(decision, "SELL", gold_tick, mt5_info) is None


def test_missing_stop_is_rejected(gold_tick, mt5_info) -> None:
    assert _stop_distance({"entry": 2500.0}, "BUY", gold_tick, mt5_info) is None


def test_fx_major_buy_price_stop_becomes_distance(eurusd_tick, fx_info) -> None:
    decision = {"entry": 1.0850, "stop": 1.0800}
    assert _stop_distance(decision, "BUY", eurusd_tick, fx_info) == pytest.approx(0.0051, abs=1e-4)


def test_jpy_major_sell_price_stop_becomes_distance(usdjpy_tick, jpy_info) -> None:
    decision = {"entry": 149.88, "stop": 150.38}
    assert _stop_distance(decision, "SELL", usdjpy_tick, jpy_info) == pytest.approx(0.5, abs=0.02)


# ---------------------------------------------------------------------------
# Minimum-volume rounding safety
# ---------------------------------------------------------------------------


def test_volume_below_minimum_is_not_rounded_up(mt5_info) -> None:
    """A computed volume smaller than the broker minimum must be rejected,
    never bumped up to volume_min — that would silently increase risk
    beyond what was approved."""
    assert _normalize_volume(mt5_info, 0.004) is None


def test_volume_rounds_down_to_preserve_risk(mt5_info) -> None:
    assert _normalize_volume(mt5_info, 0.019) == 0.01


def test_volume_at_exact_minimum_is_accepted(mt5_info) -> None:
    assert _normalize_volume(mt5_info, 0.01) == 0.01


def test_volume_above_maximum_is_clipped_down(mt5_info) -> None:
    info = SimpleNamespace(**{**mt5_info.__dict__, "volume_max": 1.0})
    assert _normalize_volume(info, 5.0) == 1.0


# ---------------------------------------------------------------------------
# place_order rejects rather than inflates an unsafe minimum lot
# ---------------------------------------------------------------------------


class _FakeMT5:
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    TRADE_ACTION_DEAL = 1
    ORDER_TIME_GTC = 0
    ORDER_FILLING_IOC = 1
    ORDER_FILLING_FOK = 2
    ORDER_FILLING_RETURN = 0

    def __init__(self, info: SimpleNamespace, tick: SimpleNamespace, account: SimpleNamespace) -> None:
        self._info = info
        self._tick = tick
        self._account = account

    def symbol_select(self, *_a, **_k) -> bool:
        return True

    def symbol_info(self, *_a, **_k):
        return self._info

    def symbol_info_tick(self, *_a, **_k):
        return self._tick

    def account_info(self):
        return self._account

    def history_deals_get(self, *_a, **_k):
        return []

    def order_check(self, *_a, **_k):
        return SimpleNamespace()


def test_place_order_rejects_when_minimum_lot_exceeds_risk_budget(
    monkeypatch: pytest.MonkeyPatch, isolated_risk_state, mt5_info, gold_tick
) -> None:
    account = SimpleNamespace(equity=10_000.0, trade_allowed=True, trade_expert=True)
    fake = _FakeMT5(mt5_info, gold_tick, account)
    monkeypatch.setattr("trading_desk.mt5_broker.connect", lambda: fake)
    monkeypatch.setattr("trading_desk.mt5_broker.shutdown", lambda: None)

    # A tiny approved size with a wide stop computes to well under one
    # minimum lot; the fix must reject, not round up to volume_min.
    decision = {
        "action": "BUY",
        "verdict": "APPROVE",
        "size_pct": 0.01,
        "entry": 2500.0,
        "stop": 2000.0,
    }
    result = place_order(UNIVERSE["gold"], decision, live=False)

    assert result["status"] == "skipped"
    assert "minimum" in result["reason"].lower()
    assert "risk" in result["reason"].lower()
