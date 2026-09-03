"""Known safety gap: paper MT5 previously recorded a position as open
even when order_check() reported the request was invalid (e.g.
insufficient margin, invalid volume). MetaTrader5's own docs warn that
accepting an order request is not proof it can be executed — order_check
must be honored, or paper state and any later promotion to live both
inherit a position that was never actually valid."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from trading_desk.instruments import UNIVERSE
from trading_desk.mt5_broker import place_order


class _FakeMT5:
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    TRADE_ACTION_DEAL = 1
    ORDER_TIME_GTC = 0
    ORDER_FILLING_IOC = 1
    ORDER_FILLING_FOK = 2
    ORDER_FILLING_RETURN = 0
    TRADE_RETCODE_DONE = 10009
    TRADE_RETCODE_INVALID_VOLUME = 10014

    def __init__(self, info, tick, account, check_retcode: int) -> None:
        self._info = info
        self._tick = tick
        self._account = account
        self._check_retcode = check_retcode

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
        return SimpleNamespace(retcode=self._check_retcode, comment="fixture")


def _place(monkeypatch: pytest.MonkeyPatch, mt5_info, gold_tick, check_retcode: int):
    account = SimpleNamespace(equity=10_000.0, trade_allowed=True, trade_expert=True)
    fake = _FakeMT5(mt5_info, gold_tick, account, check_retcode)
    monkeypatch.setattr("trading_desk.mt5_broker.connect", lambda: fake)
    monkeypatch.setattr("trading_desk.mt5_broker.shutdown", lambda: None)
    decision = {"action": "BUY", "verdict": "APPROVE", "size_pct": 1.0, "entry": 2500.0, "stop": 2475.0}
    return place_order(UNIVERSE["gold"], decision, live=False)


def test_paper_order_is_not_recorded_open_when_order_check_fails(
    monkeypatch: pytest.MonkeyPatch, isolated_risk_state, mt5_info, gold_tick
) -> None:
    from trading_desk import risk

    result = _place(monkeypatch, mt5_info, gold_tick, check_retcode=_FakeMT5.TRADE_RETCODE_INVALID_VOLUME)

    assert result["status"] == "rejected"
    assert risk.open_positions() == {}


def test_paper_order_is_recorded_open_when_order_check_passes(
    monkeypatch: pytest.MonkeyPatch, isolated_risk_state, mt5_info, gold_tick
) -> None:
    from trading_desk import risk

    result = _place(monkeypatch, mt5_info, gold_tick, check_retcode=_FakeMT5.TRADE_RETCODE_DONE)

    assert result["status"] == "paper"
    assert risk.open_positions() != {}
