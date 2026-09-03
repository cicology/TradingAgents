"""Shared offline fixtures for the desk regression suite.

Every fixture here is a plain in-memory object (SimpleNamespace/dict) —
nothing touches the network, a broker terminal, or an LLM provider. Tests
that need on-disk risk state get an isolated STATE_PATH so runs never
collide with a developer's real `trading_desk/reports/risk_state.json`.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Broker responses (MT5 symbol/account/tick shapes)
# ---------------------------------------------------------------------------


@pytest.fixture
def mt5_info() -> SimpleNamespace:
    """A typical MT5 symbol_info() for a metal CFD (XAUUSD-shaped)."""
    return SimpleNamespace(
        point=0.01,
        digits=2,
        trade_contract_size=100.0,
        trade_tick_size=0.01,
        trade_tick_value=1.0,
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
        filling_mode=1,
    )


@pytest.fixture
def fx_info() -> SimpleNamespace:
    """A typical MT5 symbol_info() for a 5-digit FX major (EURUSD-shaped)."""
    return SimpleNamespace(
        point=0.00001,
        digits=5,
        trade_contract_size=100000.0,
        trade_tick_size=0.00001,
        trade_tick_value=1.0,
        volume_min=0.01,
        volume_max=50.0,
        volume_step=0.01,
        filling_mode=1,
    )


@pytest.fixture
def jpy_info() -> SimpleNamespace:
    """A typical MT5 symbol_info() for a JPY-quoted FX major (USDJPY-shaped)."""
    return SimpleNamespace(
        point=0.001,
        digits=3,
        trade_contract_size=100000.0,
        trade_tick_size=0.001,
        trade_tick_value=1.0,
        volume_min=0.01,
        volume_max=50.0,
        volume_step=0.01,
        filling_mode=1,
    )


@pytest.fixture
def gold_tick() -> SimpleNamespace:
    return SimpleNamespace(bid=2499.90, ask=2500.10)


@pytest.fixture
def eurusd_tick() -> SimpleNamespace:
    return SimpleNamespace(bid=1.08495, ask=1.08510)


@pytest.fixture
def usdjpy_tick() -> SimpleNamespace:
    return SimpleNamespace(bid=149.870, ask=149.885)


@pytest.fixture
def mt5_account() -> SimpleNamespace:
    return SimpleNamespace(
        login=1000001,
        name="Oryares Test",
        server="Broker-Demo",
        company="Broker Ltd",
        currency="USD",
        balance=10_000.0,
        equity=10_000.0,
        margin_free=9_500.0,
        trade_allowed=True,
        trade_expert=True,
    )


# ---------------------------------------------------------------------------
# Market snapshots
# ---------------------------------------------------------------------------


@pytest.fixture
def market_snapshot() -> dict[str, Any]:
    return {
        "instrument": "gold",
        "source": "fixture",
        "daily": {
            "last_close": 2500.0,
            "rsi_14": 30.0,
            "macd_hist": 1.0,
            "atr_14": 25.0,
        },
        "intraday": None,
        "intraday_source": None,
        "headlines": [],
        "cross_asset": {},
        "recent_closes": [2490.0, 2495.0, 2500.0],
    }


# ---------------------------------------------------------------------------
# Signals / decisions
# ---------------------------------------------------------------------------


@pytest.fixture
def approved_decision() -> dict[str, Any]:
    """A fully-formed trader+risk proposal shaped like `pipeline._normalize_decision` input."""
    return {
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


@pytest.fixture
def rejected_decision() -> dict[str, Any]:
    return {
        "action": "HOLD",
        "verdict": "REJECT",
        "confidence": 35,
        "entry": None,
        "stop": None,
        "targets": [],
        "size_pct": 0,
        "max_size_pct": 0,
        "rationale": "fixture reject",
        "risks": [],
    }


# ---------------------------------------------------------------------------
# Risk decisions / lifecycle events
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_risk_state(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Point trading_desk.risk at a throwaway state file for this test only."""
    from trading_desk import risk

    state_path = tmp_path / "risk_state.json"
    monkeypatch.setattr(risk, "STATE_PATH", state_path)
    return risk


@pytest.fixture
def lifecycle_open_event() -> dict[str, Any]:
    return {
        "type": "open",
        "venue": "mt5",
        "symbol": "XAUUSD",
        "side": "BUY",
        "size_pct": 0.5,
    }


@pytest.fixture
def lifecycle_close_event() -> dict[str, Any]:
    return {
        "type": "close",
        "venue": "mt5",
        "symbol": "XAUUSD",
        "realized_pnl_pct": -0.4,
    }
