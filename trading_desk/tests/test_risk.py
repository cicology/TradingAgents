"""TA-006: shared risk state must be reconciliable — any existing position
blocks a new entry on the same venue+symbol (not just the same side), a
close event clears it and rolls PnL, and state writes are atomic so a
crash mid-write cannot corrupt the file restart recovers from."""

from __future__ import annotations

import json

import pytest

from trading_desk import risk


def test_existing_position_blocks_same_direction(isolated_risk_state) -> None:
    risk.record_open("mt5", "XAUUSD", "BUY", size_pct=0.5)

    assert not risk.check_order("mt5", "XAUUSD", "BUY", 0.5).approved


def test_existing_position_blocks_opposite_direction_too(isolated_risk_state) -> None:
    """A same-key opposite-side order would previously overwrite the
    tracked position in record_open's dict assignment, silently losing
    the original position from risk state. Any existing position must
    block a new entry on that venue+symbol, regardless of side."""
    risk.record_open("mt5", "XAUUSD", "BUY", size_pct=0.5)

    assert not risk.check_order("mt5", "XAUUSD", "SELL", 0.5).approved


def test_close_clears_position_and_updates_daily_pnl(isolated_risk_state) -> None:
    risk.record_open("mt5", "XAUUSD", "BUY", size_pct=0.5)

    risk.record_close("mt5", "XAUUSD", realized_pnl_pct=-0.4)

    assert risk.open_positions() == {}
    breached, pnl = risk.daily_loss_breached()
    assert not breached
    assert pnl == pytest.approx(-0.4)
    assert json.loads(risk.STATE_PATH.read_text())["daily"]["realized_pnl_pct"] == pytest.approx(-0.4)


def test_close_then_reopen_is_allowed(isolated_risk_state) -> None:
    risk.record_open("mt5", "XAUUSD", "BUY", size_pct=0.5)
    risk.record_close("mt5", "XAUUSD")

    assert risk.check_order("mt5", "XAUUSD", "SELL", 0.5).approved


def test_open_positions_from_different_symbols_do_not_collide(isolated_risk_state) -> None:
    risk.record_open("mt5", "XAUUSD", "BUY", size_pct=0.5)
    risk.record_open("mt5", "EURUSD", "SELL", size_pct=0.5)

    positions = risk.open_positions()
    assert set(positions) == {"MT5:XAUUSD", "MT5:EURUSD"}


def test_open_positions_are_isolated_per_venue(isolated_risk_state) -> None:
    risk.record_open("mt5", "BTCUSD", "BUY", size_pct=0.5)
    risk.record_open("binance", "BTCUSD", "SELL", size_pct=0.5)

    positions = risk.open_positions()
    assert set(positions) == {"MT5:BTCUSD", "BINANCE:BTCUSD"}


def test_record_open_persists_approved_size(isolated_risk_state) -> None:
    risk.record_open("mt5", "XAUUSD", "BUY", size_pct=1.25)

    position = risk.open_positions()["MT5:XAUUSD"]
    assert position["size_pct"] == 1.25


def test_state_write_is_atomic_no_partial_file_left_behind(isolated_risk_state, tmp_path) -> None:
    risk.record_open("mt5", "XAUUSD", "BUY", size_pct=0.5)

    # The temp file used for atomic replace must never be left on disk.
    leftovers = list(tmp_path.glob("*.tmp"))
    assert leftovers == []
    assert risk.STATE_PATH.is_file()
