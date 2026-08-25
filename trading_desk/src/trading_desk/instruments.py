from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Instrument:
    name: str
    symbol: str
    asset_class: str
    description: str
    binance_perp: str | None = None


UNIVERSE: dict[str, Instrument] = {
    "gold": Instrument(
        "gold", "GC=F", "metal", "Gold (Binance XAUUSDT TradFi perp; Yahoo GC=F fallback)", "XAUUSDT"
    ),
    "silver": Instrument(
        "silver", "SI=F", "metal", "Silver (Binance XAGUSDT TradFi perp; Yahoo SI=F fallback)", "XAGUSDT"
    ),
    "us500": Instrument(
        "us500", "^GSPC", "index", "S&P 500 (Binance SPXUSDT perp; Yahoo ^GSPC fallback)", "SPXUSDT"
    ),
    "nas100": Instrument(
        "nas100", "^NDX", "index", "Nasdaq-100 proxy (Binance QQQUSDT; Yahoo ^NDX fallback)", "QQQUSDT"
    ),
    "dxy": Instrument("dxy", "DX-Y.NYB", "fx", "US Dollar Index (Yahoo)"),
    "vix": Instrument("vix", "^VIX", "vol", "CBOE Volatility Index (Yahoo)"),
    "btc": Instrument("btc", "BTC-USD", "crypto", "Bitcoin (Binance BTCUSDT; Yahoo BTC-USD fallback)", "BTCUSDT"),
    "eth": Instrument("eth", "ETH-USD", "crypto", "Ethereum (Binance ETHUSDT; Yahoo ETH-USD fallback)", "ETHUSDT"),
}

CONTEXT_INSTRUMENTS = (
    UNIVERSE["dxy"],
    UNIVERSE["vix"],
)


def resolve(names: list[str]) -> list[Instrument]:
    resolved: list[Instrument] = []
    seen: set[str] = set()
    for raw in names:
        key = raw.strip().lower()
        if key not in UNIVERSE:
            known = ", ".join(UNIVERSE)
            raise SystemExit(f"Unknown instrument '{raw}'. Known names: {known}")
        if key not in seen:
            seen.add(key)
            resolved.append(UNIVERSE[key])
    return resolved
