"""TA-201: closed-bar MT5 data ingestion. Never returns the currently
forming bar, flags stale data explicitly, and parses deterministically
(same raw rows -> identical Bar objects every call)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from trading_desk.market_data import Bar, fetch_closed_bars, is_fresh


class _FakeMT5:
    TIMEFRAME_M15 = "M15"
    TIMEFRAME_H1 = "H1"

    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows
        self.last_call = None

    def copy_rates_from_pos(self, symbol: str, timeframe, start_pos: int, count: int):
        self.last_call = (symbol, timeframe, start_pos, count)
        return self._rows[start_pos : start_pos + count]


def _row(ts: int, o=2500.0, h=2505.0, l=2495.0, c=2502.0, v=100) -> dict:
    return {"time": ts, "open": o, "high": h, "low": l, "close": c, "tick_volume": v}


def test_fetch_closed_bars_skips_the_forming_bar() -> None:
    forming = _row(2000, c=9999.0)  # would be position 0 if not skipped
    closed_2 = _row(1000)
    closed_1 = _row(0)
    fake = _FakeMT5([forming, closed_2, closed_1])

    bars = fetch_closed_bars(fake, "XAUUSD", "1h", count=2)

    assert len(bars) == 2
    assert all(bar.close != 9999.0 for bar in bars)
    assert fake.last_call == ("XAUUSD", "H1", 1, 2)


def test_fetch_closed_bars_parses_deterministically() -> None:
    fake = _FakeMT5([_row(2000), _row(1000, c=2510.0), _row(0, c=2490.0)])

    first = fetch_closed_bars(fake, "XAUUSD", "15m", count=2)
    second = fetch_closed_bars(fake, "XAUUSD", "15m", count=2)

    assert first == second
    assert first[0].close == 2510.0


def test_fetch_closed_bars_rejects_unsupported_horizon() -> None:
    fake = _FakeMT5([_row(0)])
    with pytest.raises(ValueError, match="unsupported horizon"):
        fetch_closed_bars(fake, "XAUUSD", "1d", count=1)


def test_fetch_closed_bars_returns_empty_list_when_no_data() -> None:
    fake = _FakeMT5([])
    assert fetch_closed_bars(fake, "XAUUSD", "1h", count=5) == []


def test_bar_time_is_timezone_aware_utc() -> None:
    fake = _FakeMT5([_row(1000, c=100.0), _row(0, c=99.0)])
    bars = fetch_closed_bars(fake, "XAUUSD", "1h", count=1)
    assert bars[0].time.tzinfo is timezone.utc


def test_is_fresh_within_budget() -> None:
    now = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)
    bar = Bar(time=datetime(2026, 9, 3, 11, 50, tzinfo=timezone.utc), open=1, high=1, low=1, close=1, volume=0)
    assert is_fresh(bar, horizon="15m", now=now) is True


def test_is_fresh_rejects_stale_bar() -> None:
    now = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)
    bar = Bar(time=datetime(2026, 9, 3, 10, 0, tzinfo=timezone.utc), open=1, high=1, low=1, close=1, volume=0)
    assert is_fresh(bar, horizon="15m", now=now) is False


def test_is_fresh_rejects_empty_bar_list_semantics() -> None:
    with pytest.raises(ValueError, match="unsupported horizon"):
        is_fresh(
            Bar(time=datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc), open=1, high=1, low=1, close=1, volume=0),
            horizon="4h",
            now=datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc),
        )
