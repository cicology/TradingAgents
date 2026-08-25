from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import certifi
import httpx
import pandas as pd

from trading_desk.indicators import snapshot
from trading_desk.instruments import CONTEXT_INSTRUMENTS, Instrument

BINANCE_KLINES = "https://fapi.binance.com/fapi/v1/klines"
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
YAHOO_SEARCH = "https://query1.finance.yahoo.com/v1/finance/search"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; OryaresDesk/0.1; research)",
    "Accept": "application/json",
}


def _client() -> httpx.Client:
    return httpx.Client(timeout=30.0, headers=HEADERS, verify=certifi.where())


def _klines_to_frame(rows: list[list[Any]]) -> pd.DataFrame:
    records = []
    for row in rows:
        records.append(
            {
                "Date": datetime.fromtimestamp(int(row[0]) / 1000, tz=timezone.utc),
                "Open": float(row[1]),
                "High": float(row[2]),
                "Low": float(row[3]),
                "Close": float(row[4]),
                "Volume": float(row[5]),
            }
        )
    if not records:
        raise RuntimeError("Binance returned no klines.")
    return pd.DataFrame(records).set_index("Date")


def _binance_history(perp: str, period: str, interval: str) -> pd.DataFrame:
    mapping = {
        ("1y", "1d"): ("1d", 365),
        ("6mo", "1d"): ("1d", 200),
        ("5d", "1h"): ("1h", 120),
    }
    binance_interval, limit = mapping.get((period, interval), ("1d", 365))
    with _client() as client:
        response = client.get(
            BINANCE_KLINES,
            params={"symbol": perp, "interval": binance_interval, "limit": limit},
        )
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, list):
        raise RuntimeError(f"Unexpected Binance payload for {perp}: {payload}")
    return _klines_to_frame(payload)


def _yahoo_chart(symbol: str, period: str, interval: str) -> pd.DataFrame:
    url = YAHOO_CHART.format(symbol=quote(symbol, safe=""))
    with _client() as client:
        response = client.get(url, params={"range": period, "interval": interval, "events": "div,splits"})
        response.raise_for_status()
        payload = response.json()
    result = ((payload.get("chart") or {}).get("result") or [None])[0]
    if not result:
        raise RuntimeError(f"Yahoo chart empty for {symbol}")
    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    rows = []
    for i, ts in enumerate(timestamps):
        close_list = quote.get("close") or []
        if i >= len(close_list) or close_list[i] is None:
            continue
        rows.append(
            {
                "Open": (quote.get("open") or [None])[i],
                "High": (quote.get("high") or [None])[i],
                "Low": (quote.get("low") or [None])[i],
                "Close": close_list[i],
                "Volume": (quote.get("volume") or [0])[i] if i < len(quote.get("volume") or []) else 0,
                "Date": datetime.fromtimestamp(ts, tz=timezone.utc),
            }
        )
    if not rows:
        raise RuntimeError(f"No Yahoo bars for {symbol} ({period} {interval}).")
    return pd.DataFrame(rows).set_index("Date")


def _history(instrument: Instrument, period: str = "1y", interval: str = "1d") -> tuple[pd.DataFrame, str]:
    errors: list[str] = []
    if instrument.binance_perp:
        try:
            return _binance_history(instrument.binance_perp, period, interval), f"binance:{instrument.binance_perp}"
        except Exception as exc:  # noqa: BLE001
            errors.append(f"binance:{exc}")
    try:
        return _yahoo_chart(instrument.symbol, period, interval), f"yahoo-chart:{instrument.symbol}"
    except Exception as exc:  # noqa: BLE001
        errors.append(f"yahoo-chart:{exc}")
    raise RuntimeError("All market feeds failed: " + " | ".join(errors))


def load_daily(instrument: Instrument) -> tuple[pd.DataFrame, str]:
    return _history(instrument, period="1y", interval="1d")


def _headlines(instrument: Instrument, limit: int = 8) -> list[dict[str, Any]]:
    try:
        with _client() as client:
            response = client.get(
                YAHOO_SEARCH,
                params={"q": instrument.symbol, "newsCount": limit, "quotesCount": 0},
            )
            response.raise_for_status()
            news = response.json().get("news") or []
        return [
            {"title": str(row["title"]), "publisher": row.get("publisher")}
            for row in news[:limit]
            if row.get("title")
        ]
    except Exception:
        return []


def _context() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for instrument in CONTEXT_INSTRUMENTS:
        try:
            df, source = _history(instrument, period="6mo")
            snap = snapshot(df)
            out[instrument.name] = {
                "source": source,
                "last_close": snap["last_close"],
                "day_change_pct": snap["day_change_pct"],
                "rsi_14": snap["rsi_14"],
                "ret_21d_pct": snap["ret_21d_pct"],
            }
        except Exception as exc:  # noqa: BLE001
            out[instrument.name] = {"error": str(exc)}
    return out


def load_market(instrument: Instrument) -> dict[str, Any]:
    daily, source = _history(instrument, period="1y", interval="1d")
    pack = {
        "instrument": {
            "name": instrument.name,
            "symbol": instrument.symbol,
            "asset_class": instrument.asset_class,
            "description": instrument.description,
            "binance_perp": instrument.binance_perp,
        },
        "source": source,
        "daily": snapshot(daily),
        "headlines": _headlines(instrument),
        "cross_asset": _context(),
        "recent_closes": [
            {
                "date": str(idx.date()) if hasattr(idx, "date") else str(idx),
                "close": round(float(row["Close"]), 4),
            }
            for idx, row in daily.tail(10).iterrows()
        ],
    }
    try:
        hourly, intra_source = _history(instrument, period="5d", interval="1h")
        pack["intraday"] = snapshot(hourly) if len(hourly) >= 30 else {"note": "Not enough hourly bars"}
        pack["intraday_source"] = intra_source
    except Exception as exc:  # noqa: BLE001
        pack["intraday"] = {"error": str(exc)}
    return pack
