from __future__ import annotations

from typing import Any

import pandas as pd


def _series(df: pd.DataFrame, name: str) -> pd.Series:
    if name in df.columns:
        return pd.to_numeric(df[name], errors="coerce")
    raise KeyError(name)


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    return 100 - (100 / (1 + rs))


def ema(close: pd.Series, span: int) -> pd.Series:
    return close.ewm(span=span, adjust=False).mean()


def macd(close: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    line = ema(close, 12) - ema(close, 26)
    signal = line.ewm(span=9, adjust=False).mean()
    hist = line - signal
    return line, signal, hist


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = _series(df, "High")
    low = _series(df, "Low")
    close = _series(df, "Close")
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def snapshot(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty or len(df) < 30:
        raise ValueError("Not enough bars to compute indicators (need ~30+ daily closes).")

    close = _series(df, "Close")
    high = _series(df, "High")
    low = _series(df, "Low")
    volume = _series(df, "Volume") if "Volume" in df.columns else pd.Series(0, index=df.index)

    macd_line, macd_signal, macd_hist = macd(close)
    rsi_series = rsi(close)
    atr_series = atr(df)
    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean() if len(df) >= 200 else pd.Series(pd.NA, index=df.index)

    last = df.iloc[-1]
    prev = df.iloc[-2]
    last_close = float(close.iloc[-1])
    change = last_close - float(close.iloc[-2])
    change_pct = (change / float(close.iloc[-2])) * 100 if float(close.iloc[-2]) else 0.0

    week = close.tail(5)
    month = close.tail(21)
    year = close.tail(252) if len(close) >= 60 else close

    def ret(series: pd.Series) -> float | None:
        if len(series) < 2 or pd.isna(series.iloc[0]) or float(series.iloc[0]) == 0:
            return None
        return round((float(series.iloc[-1]) / float(series.iloc[0]) - 1) * 100, 2)

    def f(value: Any, digits: int = 2) -> float | None:
        if value is None or pd.isna(value):
            return None
        return round(float(value), digits)

    return {
        "as_of": str(df.index[-1].date()) if hasattr(df.index[-1], "date") else str(df.index[-1]),
        "last_close": f(last_close, 4),
        "prior_close": f(prev["Close"], 4),
        "day_change_pct": round(change_pct, 2),
        "day_high": f(last["High"], 4),
        "day_low": f(last["Low"], 4),
        "volume": f(volume.iloc[-1], 0),
        "rsi_14": f(rsi_series.iloc[-1], 1),
        "macd": f(macd_line.iloc[-1], 4),
        "macd_signal": f(macd_signal.iloc[-1], 4),
        "macd_hist": f(macd_hist.iloc[-1], 4),
        "atr_14": f(atr_series.iloc[-1], 4),
        "sma_20": f(sma20.iloc[-1], 4),
        "sma_50": f(sma50.iloc[-1], 4),
        "sma_200": f(sma200.iloc[-1], 4),
        "ret_5d_pct": ret(week),
        "ret_21d_pct": ret(month),
        "ret_ytd_like_pct": ret(year),
        "range_position_20d": _range_position(close.tail(20), high.tail(20), low.tail(20)),
    }


def _range_position(close: pd.Series, high: pd.Series, low: pd.Series) -> float | None:
    hi = float(high.max())
    lo = float(low.min())
    if hi == lo:
        return None
    return round((float(close.iloc[-1]) - lo) / (hi - lo) * 100, 1)
