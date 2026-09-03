"""MetaTrader 5 adapter. Terminal must be running and logged in.

Live deals require DESK_ALLOW_LIVE_ORDERS=1. Default is paper (order_check only).
This cannot guarantee profit. It only routes sized orders to your broker.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from trading_desk.instruments import Instrument
from trading_desk.mt5_config import (
    DEVIATION,
    MAGIC,
    live_orders_allowed,
    max_daily_loss_pct,
    mt5_symbol_for,
    terminal_path,
)


def _mt5():
    try:
        import MetaTrader5 as mt5
    except ImportError as exc:
        raise RuntimeError(
            "MetaTrader5 package is not installed. From trading_desk run: pip install MetaTrader5"
        ) from exc
    return mt5


def connect() -> Any:
    mt5 = _mt5()
    path = terminal_path()
    ok = mt5.initialize(path) if path else mt5.initialize()
    if not ok:
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
    return mt5


def shutdown() -> None:
    try:
        _mt5().shutdown()
    except Exception:
        pass


def _as_dict(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if hasattr(obj, "_asdict"):
        data = obj._asdict()
        out = {}
        for key, value in data.items():
            if hasattr(value, "_asdict"):
                out[key] = _as_dict(value)
            else:
                out[key] = value
        return out
    return {"value": obj}


def ping() -> dict[str, Any]:
    mt5 = connect()
    try:
        info = mt5.terminal_info()
        account = mt5.account_info()
        return {
            "ok": True,
            "terminal": _as_dict(info),
            "account": {
                "login": getattr(account, "login", None),
                "name": getattr(account, "name", None),
                "server": getattr(account, "server", None),
                "company": getattr(account, "company", None),
                "currency": getattr(account, "currency", None),
                "balance": getattr(account, "balance", None),
                "equity": getattr(account, "equity", None),
                "margin_free": getattr(account, "margin_free", None),
                "trade_allowed": getattr(account, "trade_allowed", None),
                "trade_expert": getattr(account, "trade_expert", None),
            },
        }
    finally:
        shutdown()


def account() -> dict[str, Any]:
    return ping()["account"]


def positions() -> list[dict[str, Any]]:
    mt5 = connect()
    try:
        rows = mt5.positions_get() or []
        return [_as_dict(row) for row in rows]
    finally:
        shutdown()


def quote(instrument: Instrument) -> dict[str, Any]:
    symbol = mt5_symbol_for(instrument)
    if not symbol:
        raise RuntimeError(f"{instrument.name} has no MT5 symbol mapping")
    mt5 = connect()
    try:
        if not mt5.symbol_select(symbol, True):
            raise RuntimeError(f"MT5 symbol_select failed for {symbol}: {mt5.last_error()}")
        info = mt5.symbol_info(symbol)
        tick = mt5.symbol_info_tick(symbol)
        if info is None or tick is None:
            raise RuntimeError(f"No quote for {symbol}. Add it to Market Watch. last_error={mt5.last_error()}")
        return {
            "desk": instrument.name,
            "mt5_symbol": symbol,
            "bid": tick.bid,
            "ask": tick.ask,
            "spread": round(tick.ask - tick.bid, 8) if tick.ask and tick.bid else None,
            "digits": info.digits,
            "point": info.point,
            "volume_min": info.volume_min,
            "volume_max": info.volume_max,
            "volume_step": info.volume_step,
            "trade_mode": info.trade_mode,
        }
    finally:
        shutdown()


def _filling_mode(mt5: Any, info: Any) -> int:
    filling = int(getattr(info, "filling_mode", 0) or 0)
    ioc = getattr(mt5, "ORDER_FILLING_IOC", 1)
    fok = getattr(mt5, "ORDER_FILLING_FOK", 2)
    ret = getattr(mt5, "ORDER_FILLING_RETURN", 0)
    if filling & 1:
        return fok
    if filling & 2:
        return ioc
    return ret


def _normalize_volume(info: Any, volume: float) -> float:
    step = float(info.volume_step or 0.01)
    vmin = float(info.volume_min or step)
    vmax = float(info.volume_max or volume)
    steps = round(volume / step)
    sized = max(vmin, min(vmax, steps * step))
    digits = 0 if step >= 1 else len(str(step).rstrip("0").split(".")[-1])
    return float(f"{sized:.{digits}f}")


def lots_from_risk(info: Any, tick: Any, equity: float, size_pct: float, stop_distance: float | None) -> float:
    """Convert Kelly % of equity into lots. Prefers stop-distance risk; falls back to small notional."""
    risk_money = max(0.0, equity * (size_pct / 100.0))
    if risk_money <= 0:
        return 0.0
    point = float(info.point or 0.01)
    contract = float(getattr(info, "trade_contract_size", 0) or 0) or 100.0
    tick_size = float(getattr(info, "trade_tick_size", 0) or 0) or point
    tick_value = float(getattr(info, "trade_tick_value", 0) or 0)
    price = float(tick.ask or tick.bid or 0)
    if stop_distance and stop_distance > 0 and tick_value > 0 and tick_size > 0:
        loss_per_lot = (stop_distance / tick_size) * tick_value
        if loss_per_lot > 0:
            return risk_money / loss_per_lot
    if price > 0 and contract > 0:
        # Fallback: treat size_pct as notional fraction, tiny vs true Kelly risk
        notional = risk_money
        return notional / (price * contract / 100.0) if contract >= 10 else notional / price
    return float(info.volume_min or 0.01)


def _stop_distance(decision: dict[str, Any], tick: Any, info: Any) -> float | None:
    stop = decision.get("stop")
    entry = decision.get("entry")
    atr = None
    try:
        stop_f = float(stop)
    except (TypeError, ValueError):
        return None
    try:
        entry_f = float(entry) if entry is not None else None
    except (TypeError, ValueError):
        entry_f = None
    price = float(tick.ask or tick.bid or 0)
    if entry_f and abs(entry_f - stop_f) / max(price, 1) > 0.0001 and stop_f < price * 0.5:
        # stop looks like a price
        return abs(price - stop_f)
    if 0 < stop_f < price * 0.2:
        return stop_f  # ATR-style distance
    return None


def _daily_loss_breached(mt5: Any, equity: float) -> tuple[bool, float]:
    cap = max_daily_loss_pct()
    if cap <= 0:
        return False, 0.0
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    deals = mt5.history_deals_get(today, datetime.now(timezone.utc)) or []
    pnl = 0.0
    for deal in deals:
        pnl += float(getattr(deal, "profit", 0) or 0)
        pnl += float(getattr(deal, "swap", 0) or 0)
        pnl += float(getattr(deal, "commission", 0) or 0)
    if equity <= 0:
        return False, pnl
    lost_pct = max(0.0, -pnl / equity * 100.0)
    return lost_pct >= cap, pnl


def place_order(
    instrument: Instrument,
    decision: dict[str, Any],
    *,
    live: bool = False,
) -> dict[str, Any]:
    from trading_desk.operating_mode import require_paper_mode

    require_paper_mode(live_requested=live)

    action = str(decision.get("action") or "HOLD").upper()
    verdict = str(decision.get("verdict") or "REJECT").upper()
    size_pct = float(decision.get("size_pct") or 0)
    symbol = mt5_symbol_for(instrument)
    if not symbol:
        raise RuntimeError(f"{instrument.name} has no MT5 mapping. Set MT5_SYMBOL_{instrument.name.upper()}.")
    if action not in {"BUY", "SELL"} or verdict == "REJECT" or size_pct <= 0:
        return {
            "status": "skipped",
            "reason": "HOLD/REJECT or zero Kelly size",
            "action": action,
            "verdict": verdict,
            "mt5_symbol": symbol,
        }

    from trading_desk.risk import check_order, record_open

    gate = check_order("mt5", symbol, action, size_pct=size_pct)
    if not gate.approved:
        return {"status": "blocked", "reason": gate.reason, "mt5_symbol": symbol, "action": action}
    size_pct = gate.size_pct if gate.size_pct is not None else size_pct

    mt5 = connect()
    try:
        if not mt5.symbol_select(symbol, True):
            raise RuntimeError(f"symbol_select({symbol}) failed: {mt5.last_error()}")
        info = mt5.symbol_info(symbol)
        tick = mt5.symbol_info_tick(symbol)
        account = mt5.account_info()
        if info is None or tick is None or account is None:
            raise RuntimeError(f"Missing symbol/account data: {mt5.last_error()}")
        breached, day_pnl = _daily_loss_breached(mt5, float(account.equity))
        if breached:
            return {
                "status": "blocked",
                "reason": f"Daily loss circuit breaker ({max_daily_loss_pct()}% of equity)",
                "day_pnl": day_pnl,
                "mt5_symbol": symbol,
            }
        stop_dist = _stop_distance(decision, tick, info)
        volume = lots_from_risk(info, tick, float(account.equity), size_pct, stop_dist)
        volume = _normalize_volume(info, volume)
        if volume < float(info.volume_min or 0):
            return {"status": "skipped", "reason": "volume below broker minimum", "volume": volume}

        order_type = mt5.ORDER_TYPE_BUY if action == "BUY" else mt5.ORDER_TYPE_SELL
        price = tick.ask if action == "BUY" else tick.bid
        sl = 0.0
        tp = 0.0
        if stop_dist:
            sl = price - stop_dist if action == "BUY" else price + stop_dist
        targets = decision.get("targets") or []
        if targets:
            try:
                tp = float(targets[0])
            except (TypeError, ValueError):
                tp = 0.0

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": DEVIATION,
            "magic": MAGIC,
            "comment": "oryares-desk",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": _filling_mode(mt5, info),
        }
        check = mt5.order_check(request)
        paper = {
            "status": "paper",
            "live": False,
            "mt5_symbol": symbol,
            "side": action,
            "volume": volume,
            "price": price,
            "sl": sl,
            "tp": tp,
            "size_pct": size_pct,
            "equity": account.equity,
            "day_pnl": day_pnl,
            "check": _as_dict(check),
        }
        if not live:
            record_open("mt5", symbol, action)
            return paper
        # Unreachable in Phase 0: require_paper_mode() above already raised
        # PaperOnlyError for live=True before this function did anything.
        # Left in place for the future promotion decision that replaces the
        # guard; live_orders_allowed() remains a second, independent check.
        if not live_orders_allowed():
            paper["status"] = "blocked"
            paper["reason"] = "Set DESK_ALLOW_LIVE_ORDERS=1 to send live MT5 orders"
            return paper
        if not account.trade_allowed or not account.trade_expert:
            raise RuntimeError("MT5 account has AutoTrading disabled. Enable Algo Trading in the terminal.")
        result = mt5.order_send(request)
        filled = bool(result and result.retcode == mt5.TRADE_RETCODE_DONE)
        if filled:
            record_open("mt5", symbol, action)
        payload = {
            **paper,
            "status": "submitted" if filled else "rejected",
            "live": True,
            "result": _as_dict(result),
        }
        return payload
    finally:
        shutdown()
