"""TA-201: closed-bar MT5 data ingestion for the Phase 2 canonical
pipeline.

Distinct from `market.py` (the Yahoo/Binance research feed used by the
legacy LLM analysis path) — this reads broker-realistic OHLC bars
directly from an MT5 client, for the two approved research programs
(15m intraday, 1h swing). It never returns a bar that is still forming:
`copy_rates_from_pos(start_pos=0)` returns the currently-forming bar at
position 0, so every call here starts at position 1.

No connection management lives here — callers pass an already-connected
MT5 client (see `mt5_broker.connect()`), matching the existing adapter
pattern and keeping this module trivially testable with a fake client.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

_TIMEFRAME_ATTR = {
    "15m": "TIMEFRAME_M15",
    "1h": "TIMEFRAME_H1",
}

# A bar is stale once this many bar-intervals have passed since its close
# without a newer one appearing — a generous 2x multiple of the bar size,
# not a hair-trigger.
_FRESHNESS_BUDGET = {
    "15m": timedelta(minutes=30),
    "1h": timedelta(hours=2),
}


@dataclass(frozen=True)
class Bar:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


def _supported_horizon(horizon: str) -> str:
    if horizon not in _TIMEFRAME_ATTR:
        raise ValueError(f"unsupported horizon: {horizon!r}; supported: {sorted(_TIMEFRAME_ATTR)}")
    return horizon


def fetch_closed_bars(mt5_client: Any, mt5_symbol: str, horizon: str, count: int) -> list[Bar]:
    """Return the most recent `count` CLOSED bars for `mt5_symbol` at the
    given horizon, oldest first is not guaranteed — callers get whatever
    order the client returns (MT5 returns oldest-to-most-recent by
    position, so index 0 here is the most recently *closed* bar)."""
    _supported_horizon(horizon)
    timeframe = getattr(mt5_client, _TIMEFRAME_ATTR[horizon])
    rows = mt5_client.copy_rates_from_pos(mt5_symbol, timeframe, 1, count)
    if not rows:
        return []
    return [
        Bar(
            time=datetime.fromtimestamp(int(row["time"]), tz=timezone.utc),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row.get("tick_volume", 0)),
        )
        for row in rows
    ]


def is_fresh(bar: Bar, *, horizon: str, now: datetime) -> bool:
    """Whether `bar` (expected to be the most recently closed bar) is
    still within the freshness budget for `horizon`."""
    _supported_horizon(horizon)
    budget = _FRESHNESS_BUDGET[horizon]
    return (now - bar.time) <= budget
