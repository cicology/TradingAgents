"""TA-202: deterministic EMA-crossover strategy — the first versioned
strategy for the XAU/USD vertical slice. Purely computed from closed
bars, no LLM involved: the desk stays operable with no provider
configured (Architectural Rule 6), and a replayed run with the same bars
is bit-for-bit reproducible (see evidence.compute_evidence_hash).

This is deliberately simple (9/21 EMA cross, ATR-based stop/target) —
it exists to prove the full pipeline end to end, not to be a strategy
worth promoting. Promotion needs Phase 3's evaluation framework.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from trading_desk.indicators import atr as _atr
from trading_desk.indicators import ema as _ema
from trading_desk.market_data import Bar

MIN_BARS = 30

_STOP_ATR_MULTIPLE = 1.5
_TARGET_ATR_MULTIPLE = 3.0


def _frame(bars: list[Bar]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": [b.open for b in bars],
            "High": [b.high for b in bars],
            "Low": [b.low for b in bars],
            "Close": [b.close for b in bars],
        }
    )


def _hold(reason: str, strategy_version: str) -> dict[str, Any]:
    return {
        "action": "HOLD",
        "verdict": "REJECT",
        "entry": None,
        "stop": None,
        "targets": [],
        "rationale": reason,
        "_model": None,
        "_strategy_version": strategy_version,
    }


def ema_crossover_proposal(bars: list[Bar], *, strategy_version: str) -> dict[str, Any]:
    """Bars must be oldest-first, at least MIN_BARS of them. Returns a raw
    proposal dict shaped for validation.validate_decision()."""
    if len(bars) < MIN_BARS:
        return _hold(f"insufficient history: {len(bars)} bars, need {MIN_BARS}", strategy_version)

    df = _frame(bars)
    close = df["Close"]
    fast = _ema(close, 9)
    slow = _ema(close, 21)
    atr_series = _atr(df, 14)

    last_atr = atr_series.iloc[-1]
    if pd.isna(last_atr) or float(last_atr) <= 0:
        return _hold("ATR unavailable or non-positive", strategy_version)
    last_atr = float(last_atr)

    prev_fast, prev_slow = fast.iloc[-2], slow.iloc[-2]
    last_fast, last_slow = fast.iloc[-1], slow.iloc[-1]
    last_close = float(close.iloc[-1])

    crossed_up = bool(prev_fast <= prev_slow and last_fast > last_slow)
    crossed_down = bool(prev_fast >= prev_slow and last_fast < last_slow)

    if crossed_up:
        return {
            "action": "BUY",
            "verdict": "APPROVE",
            "entry": last_close,
            "stop": round(last_close - _STOP_ATR_MULTIPLE * last_atr, 4),
            "targets": [round(last_close + _TARGET_ATR_MULTIPLE * last_atr, 4)],
            "rationale": f"9/21 EMA crossed up at {last_close}",
            "_model": None,
            "_strategy_version": strategy_version,
        }
    if crossed_down:
        return {
            "action": "SELL",
            "verdict": "APPROVE",
            "entry": last_close,
            "stop": round(last_close + _STOP_ATR_MULTIPLE * last_atr, 4),
            "targets": [round(last_close - _TARGET_ATR_MULTIPLE * last_atr, 4)],
            "rationale": f"9/21 EMA crossed down at {last_close}",
            "_model": None,
            "_strategy_version": strategy_version,
        }
    return _hold("no crossover", strategy_version)
