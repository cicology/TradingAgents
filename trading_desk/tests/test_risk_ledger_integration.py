"""TA-105: risk.record_open()/record_close() are the single choke point
both MT5 and Binance adapters already call — wiring the immutable ledger
in here (rather than in every adapter) captures lifecycle activity across
every venue for free. A ledger write failure must never break the
safety-critical JSON risk-state gate it sits alongside."""

from __future__ import annotations

import pytest

from trading_desk import ledger, risk
from trading_desk.domain import LifecycleEventType


def test_record_open_writes_lifecycle_event_to_ledger(isolated_risk_state) -> None:
    risk.record_open("mt5", "XAUUSD", "BUY", size_pct=0.5)

    conn = ledger.connect(isolated_risk_state.LEDGER_DB_PATH)
    try:
        events = ledger.list_lifecycle_events(conn, venue="mt5", symbol="XAUUSD")
    finally:
        conn.close()

    assert len(events) == 1
    assert events[0].event_type is LifecycleEventType.OPEN
    assert events[0].payload["side"] == "BUY"
    assert events[0].payload["size_pct"] == 0.5


def test_record_close_writes_lifecycle_event_to_ledger(isolated_risk_state) -> None:
    risk.record_open("mt5", "XAUUSD", "BUY", size_pct=0.5)
    risk.record_close("mt5", "XAUUSD", realized_pnl_pct=-0.4)

    conn = ledger.connect(isolated_risk_state.LEDGER_DB_PATH)
    try:
        events = ledger.list_lifecycle_events(conn, venue="mt5", symbol="XAUUSD")
    finally:
        conn.close()

    assert [e.event_type for e in events] == [LifecycleEventType.OPEN, LifecycleEventType.CLOSE]
    assert events[1].payload["realized_pnl_pct"] == -0.4


def test_ledger_history_survives_across_open_close_open(isolated_risk_state) -> None:
    """The ledger is a full history, not a current-state snapshot like
    risk_state.json — re-opening after a close must not erase the earlier
    open/close pair."""
    risk.record_open("mt5", "XAUUSD", "BUY", size_pct=0.5)
    risk.record_close("mt5", "XAUUSD", realized_pnl_pct=0.2)
    risk.record_open("mt5", "XAUUSD", "SELL", size_pct=0.3)

    conn = ledger.connect(isolated_risk_state.LEDGER_DB_PATH)
    try:
        events = ledger.list_lifecycle_events(conn, venue="mt5", symbol="XAUUSD")
    finally:
        conn.close()

    assert [e.event_type for e in events] == [
        LifecycleEventType.OPEN,
        LifecycleEventType.CLOSE,
        LifecycleEventType.OPEN,
    ]


def test_ledger_write_failure_does_not_break_risk_state(
    isolated_risk_state, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(*_args, **_kwargs):
        raise OSError("disk full (fixture)")

    monkeypatch.setattr(ledger, "connect", _boom)

    risk.record_open("mt5", "XAUUSD", "BUY", size_pct=0.5)

    assert risk.open_positions() != {}
