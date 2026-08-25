"""Run shipped Brue example strategies on desk OHLCV (bar-by-bar subset)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from trading_desk.indicators import ema, rsi
from trading_desk.instruments import Instrument

REPO_ROOT = Path(__file__).resolve().parents[3]
BRUE_EXAMPLES = REPO_ROOT / "integrations" / "brue" / "examples"

SCRIPTS = {
    "ema_crossover": BRUE_EXAMPLES / "ema_crossover.brue",
    "rsi_extremes": BRUE_EXAMPLES / "rsi_extremes.brue",
    "correlation_returns": BRUE_EXAMPLES / "correlation_returns.brue",
    "cross_pair_zscore": BRUE_EXAMPLES / "cross_pair_zscore.brue",
}


def list_scripts() -> list[dict[str, str]]:
    rows = []
    for name, path in SCRIPTS.items():
        rows.append(
            {
                "name": name,
                "path": str(path),
                "present": path.is_file(),
                "runner": "native" if name in {"ema_crossover", "rsi_extremes"} else "unsupported",
            }
        )
    return rows


def _crossover(fast: pd.Series, slow: pd.Series) -> pd.Series:
    prev_fast = fast.shift(1)
    prev_slow = slow.shift(1)
    return (prev_fast <= prev_slow) & (fast > slow)


def _crossunder(fast: pd.Series, slow: pd.Series) -> pd.Series:
    prev_fast = fast.shift(1)
    prev_slow = slow.shift(1)
    return (prev_fast >= prev_slow) & (fast < slow)


def run_script(name: str, instrument: Instrument, daily: pd.DataFrame) -> dict[str, Any]:
    key = name.strip().lower().replace(".brue", "")
    if key not in SCRIPTS:
        known = ", ".join(SCRIPTS)
        raise SystemExit(f"Unknown Brue script '{name}'. Known: {known}")
    if key in {"correlation_returns", "cross_pair_zscore"}:
        raise SystemExit(
            f"{key} needs a second FX pair (EUR/GBP) from the Brue host. "
            "Use ema_crossover or rsi_extremes on gold/indices/crypto."
        )
    close = pd.to_numeric(daily["Close"], errors="coerce")
    source = SCRIPTS[key]
    if key == "ema_crossover":
        return _ema_crossover(instrument, close, source)
    return _rsi_extremes(instrument, close, source)


def _ema_crossover(instrument: Instrument, close: pd.Series, source: Path) -> dict[str, Any]:
    fast = ema(close, 9)
    slow = ema(close, 21)
    buys = _crossover(fast, slow).fillna(False)
    sells = _crossunder(fast, slow).fillna(False)
    last = "HOLD"
    if bool(buys.iloc[-1]):
        last = "BUY"
    elif bool(sells.iloc[-1]):
        last = "SELL"
    events = []
    for idx in close.index[-30:]:
        if bool(buys.loc[idx]):
            events.append({"date": str(idx.date()) if hasattr(idx, "date") else str(idx), "signal": "BUY"})
        elif bool(sells.loc[idx]):
            events.append({"date": str(idx.date()) if hasattr(idx, "date") else str(idx), "signal": "SELL"})
    return {
        "script": "ema_crossover",
        "source": str(source),
        "instrument": instrument.name,
        "binance_perp": instrument.binance_perp,
        "last_signal": last,
        "fast_ema": round(float(fast.iloc[-1]), 4) if pd.notna(fast.iloc[-1]) else None,
        "slow_ema": round(float(slow.iloc[-1]), 4) if pd.notna(slow.iloc[-1]) else None,
        "events_30d": events,
        "rationale": "Brue ema_crossover: BUY on fast/slow EMA cross up, SELL on cross down.",
    }


def _rsi_extremes(instrument: Instrument, close: pd.Series, source: Path) -> dict[str, Any]:
    values = rsi(close, 14)
    last_rsi = float(values.iloc[-1]) if pd.notna(values.iloc[-1]) else None
    last = "HOLD"
    if last_rsi is not None and last_rsi < 30:
        last = "BUY"
    elif last_rsi is not None and last_rsi > 70:
        last = "SELL"
    events = []
    for idx in close.index[-30:]:
        val = values.loc[idx]
        if pd.isna(val):
            continue
        if float(val) < 30:
            events.append({"date": str(idx.date()) if hasattr(idx, "date") else str(idx), "signal": "BUY", "rsi": round(float(val), 1)})
        elif float(val) > 70:
            events.append({"date": str(idx.date()) if hasattr(idx, "date") else str(idx), "signal": "SELL", "rsi": round(float(val), 1)})
    return {
        "script": "rsi_extremes",
        "source": str(source),
        "instrument": instrument.name,
        "binance_perp": instrument.binance_perp,
        "last_signal": last,
        "rsi_14": round(last_rsi, 1) if last_rsi is not None else None,
        "events_30d": events,
        "rationale": "Brue rsi_extremes: BUY below 30, SELL above 70.",
    }


def analyze_with_brue(instrument: Instrument, script: str) -> dict[str, Any]:
    from trading_desk.market import load_daily

    daily, source = load_daily(instrument)
    result = run_script(script, instrument, daily)
    result["market_source"] = source
    result["as_of"] = str(daily.index[-1].date()) if hasattr(daily.index[-1], "date") else str(daily.index[-1])
    result["last_close"] = round(float(daily["Close"].iloc[-1]), 4)
    return result
