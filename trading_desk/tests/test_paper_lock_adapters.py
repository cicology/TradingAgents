"""TA-002: every adapter side effect (MT5 terminal connect, Binance bridge
subprocess) must be unreachable for a live request — the guard has to run
*before* any network/process call, not merely reject the final result.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from trading_desk import binance_bridge, mt5_broker
from trading_desk.instruments import UNIVERSE
from trading_desk.operating_mode import PaperOnlyError


def test_mt5_place_order_rejects_live_before_connecting(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom() -> None:
        raise AssertionError("mt5_broker.connect() must not run for a rejected live request")

    monkeypatch.setattr(mt5_broker, "connect", _boom)

    decision = {"action": "BUY", "verdict": "APPROVE", "size_pct": 1.0}
    with pytest.raises(PaperOnlyError):
        mt5_broker.place_order(UNIVERSE["gold"], decision, live=True)


def test_mt5_place_order_paper_path_still_works(monkeypatch: pytest.MonkeyPatch, isolated_risk_state) -> None:
    info = SimpleNamespace(
        point=0.01,
        trade_contract_size=100.0,
        trade_tick_size=0.01,
        trade_tick_value=1.0,
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
        filling_mode=1,
    )
    tick = SimpleNamespace(bid=2499.9, ask=2500.1)
    account = SimpleNamespace(equity=10_000.0, trade_allowed=True, trade_expert=True)

    class FakeMT5:
        ORDER_TYPE_BUY = 0
        ORDER_TYPE_SELL = 1
        TRADE_ACTION_DEAL = 1
        ORDER_TIME_GTC = 0
        ORDER_FILLING_IOC = 1
        ORDER_FILLING_FOK = 2
        ORDER_FILLING_RETURN = 0
        TRADE_RETCODE_DONE = 10009

        def symbol_select(self, *_args, **_kwargs) -> bool:
            return True

        def symbol_info(self, *_args, **_kwargs):
            return info

        def symbol_info_tick(self, *_args, **_kwargs):
            return tick

        def account_info(self):
            return account

        def history_deals_get(self, *_args, **_kwargs):
            return []

        def order_check(self, *_args, **_kwargs):
            return SimpleNamespace(retcode=self.TRADE_RETCODE_DONE)

    monkeypatch.setattr(mt5_broker, "connect", lambda: FakeMT5())
    monkeypatch.setattr(mt5_broker, "shutdown", lambda: None)

    decision = {"action": "BUY", "verdict": "APPROVE", "size_pct": 1.0, "entry": 2500.0, "stop": 25.0}
    result = mt5_broker.place_order(UNIVERSE["gold"], decision, live=False)

    assert result["status"] == "paper"
    assert result["live"] is False


def test_binance_paper_order_rejects_live_before_invoking_bridge(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_args, **_kwargs):
        raise AssertionError("binance_bridge.invoke() must not run for a rejected live request")

    monkeypatch.setattr(binance_bridge, "invoke", _boom)

    with pytest.raises(PaperOnlyError):
        binance_bridge.paper_order("BTCUSDT", "BUY", 0.001, live=True)
