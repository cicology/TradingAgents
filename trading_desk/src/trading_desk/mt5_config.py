from __future__ import annotations

import os
from dataclasses import dataclass

from trading_desk.instruments import Instrument


def _env_symbol(name: str, default: str) -> str:
    key = f"MT5_SYMBOL_{name.upper()}"
    return (os.getenv(key) or default).strip()


# Broker names vary (XAUUSD vs GOLD vs XAUUSDm). Override with MT5_SYMBOL_GOLD etc.
MT5_DEFAULTS = {
    "gold": "XAUUSD",
    "silver": "XAGUSD",
    "us500": "US500",
    "nas100": "NAS100",
    "dxy": "DXY",
    "btc": "BTCUSD",
    "eth": "ETHUSD",
}


def mt5_symbol_for(instrument: Instrument) -> str | None:
    default = MT5_DEFAULTS.get(instrument.name)
    if not default:
        return None
    return _env_symbol(instrument.name, default)


def live_orders_allowed() -> bool:
    return os.getenv("DESK_ALLOW_LIVE_ORDERS", "0").strip() == "1"


def max_daily_loss_pct() -> float:
    try:
        return float(os.getenv("MT5_MAX_DAILY_LOSS_PCT", "3") or 3)
    except ValueError:
        return 3.0


def terminal_path() -> str | None:
    path = os.getenv("MT5_TERMINAL_PATH", "").strip()
    return path or None


MAGIC = 260825
DEVIATION = int(os.getenv("MT5_DEVIATION", "30") or 30)
