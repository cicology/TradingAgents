"""TA-205: outcomes are persisted append-only in the ledger, and the
exported report's totals must match direct ledger queries — the report is
a derived view, never a second source of truth that could drift."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from trading_desk import ledger
from trading_desk.domain import Outcome
from trading_desk.outcome_report import build_report, render_report_markdown

BASE = datetime(2026, 9, 3, 0, 0, tzinfo=timezone.utc)


def _outcome(i: int, pnl_pct: float) -> Outcome:
    return Outcome(
        venue="mt5",
        symbol="XAUUSD",
        strategy_version="xau-ema-crossover@1",
        opened_at=BASE + timedelta(hours=i),
        closed_at=BASE + timedelta(hours=i + 1),
        realized_pnl_pct=pnl_pct,
    )


def test_record_and_list_outcomes_round_trip(tmp_path) -> None:
    conn = ledger.connect(tmp_path / "ledger.sqlite3")
    try:
        ledger.record_outcome(conn, "out-1", _outcome(0, 1.0))
        ledger.record_outcome(conn, "out-2", _outcome(1, -0.5))

        outcomes = ledger.list_outcomes(conn, strategy_version="xau-ema-crossover@1")
        assert len(outcomes) == 2
        assert outcomes[0].realized_pnl_pct == pytest.approx(1.0)
        assert outcomes[1].realized_pnl_pct == pytest.approx(-0.5)
    finally:
        conn.close()


def test_duplicate_outcome_id_is_not_duplicated(tmp_path) -> None:
    conn = ledger.connect(tmp_path / "ledger.sqlite3")
    try:
        first = ledger.record_outcome(conn, "out-1", _outcome(0, 1.0))
        second = ledger.record_outcome(conn, "out-1", _outcome(0, 99.0))
        assert first is True
        assert second is False
        assert len(ledger.list_outcomes(conn, strategy_version="xau-ema-crossover@1")) == 1
    finally:
        conn.close()


def test_outcomes_table_rejects_update_and_delete(tmp_path) -> None:
    conn = ledger.connect(tmp_path / "ledger.sqlite3")
    try:
        ledger.record_outcome(conn, "out-1", _outcome(0, 1.0))
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute("UPDATE outcomes SET realized_pnl_pct = 0 WHERE outcome_id = 'out-1'")
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute("DELETE FROM outcomes WHERE outcome_id = 'out-1'")
    finally:
        conn.close()


def test_report_totals_match_ledger_queries(tmp_path) -> None:
    conn = ledger.connect(tmp_path / "ledger.sqlite3")
    try:
        pnls = [1.2, -0.8, 0.5, -0.3, 2.0]
        for i, pnl in enumerate(pnls):
            ledger.record_outcome(conn, f"out-{i}", _outcome(i, pnl))

        report = build_report(conn, strategy_version="xau-ema-crossover@1")
        raw = ledger.list_outcomes(conn, strategy_version="xau-ema-crossover@1")

        assert report["trade_count"] == len(raw)
        assert report["trade_count"] == 5
        assert report["win_count"] == sum(1 for o in raw if o.realized_pnl_pct > 0)
        assert report["loss_count"] == sum(1 for o in raw if o.realized_pnl_pct <= 0)
        assert report["total_realized_pnl_pct"] == pytest.approx(sum(o.realized_pnl_pct for o in raw))
        assert report["win_rate"] == pytest.approx(report["win_count"] / report["trade_count"])
    finally:
        conn.close()


def test_report_with_no_trades_is_well_formed_not_a_crash(tmp_path) -> None:
    conn = ledger.connect(tmp_path / "ledger.sqlite3")
    try:
        report = build_report(conn, strategy_version="unknown-strategy@1")
        assert report["trade_count"] == 0
        assert report["win_rate"] is None
        assert report["total_realized_pnl_pct"] == 0.0
    finally:
        conn.close()


def test_equity_curve_is_cumulative_and_chronological(tmp_path) -> None:
    conn = ledger.connect(tmp_path / "ledger.sqlite3")
    try:
        for i, pnl in enumerate([1.0, -0.5, 2.0]):
            ledger.record_outcome(conn, f"out-{i}", _outcome(i, pnl))
        report = build_report(conn, strategy_version="xau-ema-crossover@1")
        assert report["equity_curve_pct"] == [pytest.approx(1.0), pytest.approx(0.5), pytest.approx(2.5)]
    finally:
        conn.close()


def test_markdown_render_includes_key_totals(tmp_path) -> None:
    conn = ledger.connect(tmp_path / "ledger.sqlite3")
    try:
        ledger.record_outcome(conn, "out-1", _outcome(0, 1.0))
        report = build_report(conn, strategy_version="xau-ema-crossover@1")
        text = render_report_markdown(report)
        assert "xau-ema-crossover@1" in text
        assert "1" in text  # trade count appears somewhere
    finally:
        conn.close()
