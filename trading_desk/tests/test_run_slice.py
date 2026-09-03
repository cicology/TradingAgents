"""TA-206: the vertical-slice orchestrator ties TA-201-205 into one
reproducible run — market data -> evidence -> strategy -> validate ->
size -> paper order -> fill -> lifecycle replay -> ledger persistence.
This is the mission's literal deliverable for Phase 2: 'one complete,
dependable research loop for XAU/USD', proven end to end rather than as
disconnected, individually-tested pieces."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from trading_desk import ledger
from trading_desk.market_data import Bar
from trading_desk.run_slice import RunConfig, run_slice

BASE = datetime(2026, 9, 3, 0, 0, tzinfo=timezone.utc)


def _config(**overrides) -> RunConfig:
    fields = dict(
        instrument="gold",
        venue_symbol="XAUUSD",
        strategy_version="xau-ema-crossover@1",
        horizon="1h",
        equity=10_000.0,
        base_risk_pct=1.0,
        spread=0.30,
        slippage=0.10,
        commission_per_unit=0.02,
        max_holding_bars=10,
    )
    fields.update(overrides)
    return RunConfig(**fields)


def _rising_bars() -> list[Bar]:
    closes = [2550.0 - i * 3 for i in range(25)] + [2550.0 - 24 * 3 + j * 15 for j in range(1, 6)]
    return [
        Bar(time=BASE + timedelta(hours=i), open=c - 0.5, high=c + 1.0, low=c - 1.0, close=c, volume=100)
        for i, c in enumerate(closes)
    ]


def test_stale_data_is_rejected(tmp_path) -> None:
    conn = ledger.connect(tmp_path / "ledger.sqlite3")
    try:
        bars = _rising_bars()
        far_future = bars[-1].time + timedelta(days=1)
        result = run_slice(conn, bars, [], _config(), now=far_future)
        assert result.status == "rejected"
        assert "stale" in result.reason
    finally:
        conn.close()


def test_insufficient_history_is_no_trade(tmp_path) -> None:
    conn = ledger.connect(tmp_path / "ledger.sqlite3")
    try:
        bars = _rising_bars()[:5]
        result = run_slice(conn, bars, [], _config(), now=bars[-1].time)
        assert result.status == "no_trade"
        assert result.decision_id is not None
    finally:
        conn.close()


def test_full_run_with_no_subsequent_bars_opens_and_persists_decision(tmp_path) -> None:
    conn = ledger.connect(tmp_path / "ledger.sqlite3")
    try:
        bars = _rising_bars()
        result = run_slice(conn, bars, [], _config(), now=bars[-1].time)

        assert result.status == "opened"
        assert result.evidence_hash is not None
        decision = ledger.get_decision(conn, result.decision_id)
        assert decision is not None
        assert decision.action.value == "BUY"
    finally:
        conn.close()


def test_full_run_with_subsequent_bars_closes_and_persists_outcome(tmp_path) -> None:
    conn = ledger.connect(tmp_path / "ledger.sqlite3")
    try:
        bars = _rising_bars()
        entry_price = bars[-1].close
        subsequent = [
            Bar(time=bars[-1].time + timedelta(hours=1), open=entry_price + 5,
                high=entry_price + 200, low=entry_price - 1, close=entry_price + 150, volume=100),
        ]
        result = run_slice(conn, bars, subsequent, _config(), now=bars[-1].time)

        assert result.status == "closed"
        assert result.outcome_id is not None
        outcomes = ledger.list_outcomes(conn, strategy_version="xau-ema-crossover@1")
        assert len(outcomes) == 1

        lifecycle_events = ledger.list_lifecycle_events(conn, venue="mt5", symbol="XAUUSD")
        assert [e.event_type.value for e in lifecycle_events] == ["open", "close"]
    finally:
        conn.close()


def test_replaying_the_same_run_is_idempotent_in_the_ledger(tmp_path) -> None:
    conn = ledger.connect(tmp_path / "ledger.sqlite3")
    try:
        bars = _rising_bars()
        entry_price = bars[-1].close
        subsequent = [
            Bar(time=bars[-1].time + timedelta(hours=1), open=entry_price + 5,
                high=entry_price + 200, low=entry_price - 1, close=entry_price + 150, volume=100),
        ]
        first = run_slice(conn, bars, subsequent, _config(), now=bars[-1].time)
        second = run_slice(conn, bars, subsequent, _config(), now=bars[-1].time)

        assert first.decision_id == second.decision_id
        assert first.outcome_id == second.outcome_id
        assert len(ledger.list_outcomes(conn, strategy_version="xau-ema-crossover@1")) == 1
    finally:
        conn.close()


def test_no_bars_at_all_is_rejected(tmp_path) -> None:
    conn = ledger.connect(tmp_path / "ledger.sqlite3")
    try:
        result = run_slice(conn, [], [], _config(), now=BASE)
        assert result.status == "rejected"
        assert "no market data" in result.reason
    finally:
        conn.close()
