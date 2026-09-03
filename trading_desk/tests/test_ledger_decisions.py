"""E1 exit criterion: 'every decision ... is durable and traceable', not
just lifecycle events. record_decision()/get_decision() give the ledger
somewhere to persist a canonical TradeDecision, append-only and idempotent
by decision_id, ready for Phase 2's vertical slice to call."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from trading_desk import ledger
from trading_desk.domain import Action, TradeDecision, Verdict

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)


def decision(**overrides) -> TradeDecision:
    fields = dict(
        instrument="gold",
        strategy_version="xau-swing@1",
        action=Action.BUY,
        verdict=Verdict.APPROVE,
        size_pct=1.0,
        entry=2500.0,
        stop=2475.0,
        targets=(2550.0,),
        rationale="fixture",
        model="fixture-model",
        generated_at=NOW,
    )
    fields.update(overrides)
    return TradeDecision(**fields)


def test_record_and_get_decision_round_trips(tmp_path) -> None:
    conn = ledger.connect(tmp_path / "ledger.sqlite3")
    try:
        ledger.record_decision(conn, "dec-1", decision())
        fetched = ledger.get_decision(conn, "dec-1")

        assert fetched is not None
        assert fetched.instrument == "gold"
        assert fetched.action is Action.BUY
        assert fetched.verdict is Verdict.APPROVE
        assert fetched.size_pct == pytest.approx(1.0)
        assert fetched.targets == (2550.0,)
    finally:
        conn.close()


def test_get_unknown_decision_returns_none(tmp_path) -> None:
    conn = ledger.connect(tmp_path / "ledger.sqlite3")
    try:
        assert ledger.get_decision(conn, "does-not-exist") is None
    finally:
        conn.close()


def test_duplicate_decision_id_is_not_duplicated(tmp_path) -> None:
    conn = ledger.connect(tmp_path / "ledger.sqlite3")
    try:
        first = ledger.record_decision(conn, "dec-1", decision())
        second = ledger.record_decision(conn, "dec-1", decision(rationale="different"))

        assert first is True
        assert second is False
        # The original, not the attempted overwrite, is what's stored.
        assert ledger.get_decision(conn, "dec-1").rationale == "fixture"
    finally:
        conn.close()


def test_decisions_table_rejects_update_and_delete(tmp_path) -> None:
    conn = ledger.connect(tmp_path / "ledger.sqlite3")
    try:
        ledger.record_decision(conn, "dec-1", decision())
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute("UPDATE decisions SET rationale = 'changed' WHERE decision_id = 'dec-1'")
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute("DELETE FROM decisions WHERE decision_id = 'dec-1'")
    finally:
        conn.close()


def test_existing_v1_database_upgrades_cleanly_to_v2(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A database created before the decisions table existed must upgrade
    in place when reopened with the newer code — not require a fresh
    file."""
    path = tmp_path / "ledger.sqlite3"
    monkeypatch.setattr(ledger, "_MIGRATIONS", ledger._MIGRATIONS[:1])
    old_conn = ledger.connect(path)
    assert ledger.schema_version(old_conn) == 1
    old_conn.close()

    monkeypatch.undo()  # restore the real _MIGRATIONS list

    upgraded_conn = ledger.connect(path)
    try:
        assert ledger.schema_version(upgraded_conn) == 2
        assert ledger.record_decision(upgraded_conn, "dec-1", decision()) is True
    finally:
        upgraded_conn.close()


def test_reject_decision_round_trips_with_null_levels(tmp_path) -> None:
    conn = ledger.connect(tmp_path / "ledger.sqlite3")
    try:
        rejected = decision(
            action=Action.HOLD, verdict=Verdict.REJECT, size_pct=0.0, entry=None, stop=None, targets=()
        )
        ledger.record_decision(conn, "dec-2", rejected)
        fetched = ledger.get_decision(conn, "dec-2")

        assert fetched.entry is None
        assert fetched.stop is None
        assert fetched.targets == ()
    finally:
        conn.close()
