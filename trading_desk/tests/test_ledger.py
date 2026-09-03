"""TA-102/TA-105: the SQLite ledger must be durable, idempotent on
duplicate writes, restart-safe (state reconstructs from events, not an
in-memory cache), and lifecycle_events must be append-only — no UPDATE or
DELETE, enforced at the database level, not just by convention."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from trading_desk import ledger
from trading_desk.domain import LifecycleEvent, LifecycleEventType

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)


def _event(event_id: str, event_type: LifecycleEventType, **payload) -> LifecycleEvent:
    return LifecycleEvent(
        event_id=event_id,
        venue="mt5",
        symbol="XAUUSD",
        event_type=event_type,
        occurred_at=NOW,
        payload=payload,
    )


def test_fresh_db_creates_schema(tmp_path) -> None:
    conn = ledger.connect(tmp_path / "ledger.sqlite3")
    try:
        assert ledger.schema_version(conn) >= 1
    finally:
        conn.close()


def test_migrate_is_idempotent(tmp_path) -> None:
    path = tmp_path / "ledger.sqlite3"
    conn = ledger.connect(path)
    version_before = ledger.schema_version(conn)
    ledger.migrate(conn)
    ledger.migrate(conn)
    assert ledger.schema_version(conn) == version_before
    conn.close()


def test_duplicate_event_id_is_not_duplicated(tmp_path) -> None:
    conn = ledger.connect(tmp_path / "ledger.sqlite3")
    try:
        event = _event("evt-1", LifecycleEventType.OPEN, side="BUY", size_pct=0.5)
        first = ledger.record_lifecycle_event(conn, event)
        second = ledger.record_lifecycle_event(conn, event)

        assert first is True
        assert second is False
        assert len(ledger.list_lifecycle_events(conn, venue="mt5", symbol="XAUUSD")) == 1
    finally:
        conn.close()


def test_current_position_reconstructs_open_then_close(tmp_path) -> None:
    conn = ledger.connect(tmp_path / "ledger.sqlite3")
    try:
        ledger.record_lifecycle_event(conn, _event("evt-open", LifecycleEventType.OPEN, side="BUY", size_pct=0.5))
        assert ledger.current_position(conn, "mt5", "XAUUSD") is not None

        close_event = LifecycleEvent(
            event_id="evt-close",
            venue="mt5",
            symbol="XAUUSD",
            event_type=LifecycleEventType.CLOSE,
            occurred_at=NOW + timedelta(hours=1),
            payload={"realized_pnl_pct": -0.4},
        )
        ledger.record_lifecycle_event(conn, close_event)
        assert ledger.current_position(conn, "mt5", "XAUUSD") is None
    finally:
        conn.close()


def test_restart_recovery_derives_state_from_durable_events(tmp_path) -> None:
    path = tmp_path / "ledger.sqlite3"
    conn = ledger.connect(path)
    ledger.record_lifecycle_event(conn, _event("evt-open", LifecycleEventType.OPEN, side="SELL", size_pct=1.0))
    conn.close()

    reopened = ledger.connect(path)
    try:
        position = ledger.current_position(reopened, "mt5", "XAUUSD")
        assert position is not None
        assert position["side"] == "SELL"
    finally:
        reopened.close()


def test_lifecycle_events_are_ordered_chronologically(tmp_path) -> None:
    conn = ledger.connect(tmp_path / "ledger.sqlite3")
    try:
        later = LifecycleEvent(
            event_id="evt-2", venue="mt5", symbol="XAUUSD",
            event_type=LifecycleEventType.CLOSE, occurred_at=NOW + timedelta(hours=1), payload={},
        )
        earlier = _event("evt-1", LifecycleEventType.OPEN, side="BUY", size_pct=0.5)
        # Insert out of order; retrieval must still be chronological.
        ledger.record_lifecycle_event(conn, later)
        ledger.record_lifecycle_event(conn, earlier)

        events = ledger.list_lifecycle_events(conn, venue="mt5", symbol="XAUUSD")
        assert [e.event_id for e in events] == ["evt-1", "evt-2"]
    finally:
        conn.close()


def test_lifecycle_events_table_rejects_update(tmp_path) -> None:
    conn = ledger.connect(tmp_path / "ledger.sqlite3")
    try:
        ledger.record_lifecycle_event(conn, _event("evt-1", LifecycleEventType.OPEN, side="BUY", size_pct=0.5))
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute("UPDATE lifecycle_events SET symbol = 'EURUSD' WHERE event_id = 'evt-1'")
    finally:
        conn.close()


def test_lifecycle_events_table_rejects_delete(tmp_path) -> None:
    conn = ledger.connect(tmp_path / "ledger.sqlite3")
    try:
        ledger.record_lifecycle_event(conn, _event("evt-1", LifecycleEventType.OPEN, side="BUY", size_pct=0.5))
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute("DELETE FROM lifecycle_events WHERE event_id = 'evt-1'")
    finally:
        conn.close()


def test_ledger_module_exposes_no_mutation_api() -> None:
    """API-level belt-and-braces: the repository module itself must not
    offer a way to update or delete a recorded event."""
    assert not hasattr(ledger, "update_lifecycle_event")
    assert not hasattr(ledger, "delete_lifecycle_event")
