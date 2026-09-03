"""Call the Kos-M/binance Node SDK via the local bridge CLI."""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
BRIDGE_DIR = REPO_ROOT / "integrations" / "binance-bridge"
BRIDGE_ENTRY = BRIDGE_DIR / "cli.mjs"


def _node() -> str:
    exe = shutil.which("node")
    if not exe:
        raise RuntimeError("Node.js is required for the Binance SDK bridge. Install Node 18+ and retry.")
    return exe


def invoke(command: str, extra: list[str] | None = None, timeout: float = 45.0) -> dict[str, Any]:
    if not BRIDGE_ENTRY.is_file():
        raise RuntimeError(f"Missing Binance bridge at {BRIDGE_ENTRY}")
    args = [_node(), str(BRIDGE_ENTRY), command, *(extra or [])]
    env = os.environ.copy()
    completed = subprocess.run(
        args,
        cwd=str(BRIDGE_DIR),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        check=False,
    )
    stdout = (completed.stdout or "").strip()
    if completed.returncode != 0:
        err = (completed.stderr or stdout or "bridge failed").strip()
        raise RuntimeError(err)
    if not stdout:
        return {"ok": True}
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Bridge did not return JSON: {stdout[:500]}") from exc


def ping() -> dict[str, Any]:
    return invoke("ping")


def klines(symbol: str, interval: str = "1d", limit: int = 30) -> dict[str, Any]:
    return invoke("klines", [symbol, interval, str(limit)])


def quantity_from_risk(
    *,
    equity: float,
    size_pct: float,
    entry: float,
    stop: float,
    side: str = "BUY",
    step: float | None = None,
    min_qty: float | None = None,
    min_notional: float | None = None,
    fee_rate: float = 0.0,
) -> float:
    """Size a linear USD-margined Binance perp quantity from risk inputs,
    through the same deterministic pipeline MT5 sizing uses — never from a
    manually-typed quantity.

    @param size_pct: requested position size as % of equity. Clipped to the
        shared `risk.MAX_POSITION_PCT` cap regardless of what was asked for.
    @param step: exchange LOT_SIZE stepSize, if known. Quantity is floored
        to this step — never rounded up, which would size above budget.
    @param min_qty: exchange LOT_SIZE minQty, if known. A floored quantity
        below this is rejected, never bumped up to the minimum.
    @param min_notional: exchange MIN_NOTIONAL, if known. A quantity whose
        notional (quantity * entry) falls below this is rejected.
    @param fee_rate: estimated round-trip fee as a fraction of notional
        (e.g. 0.001 for 0.1%). Reduces the effective risk budget before
        sizing; it can only shrink the resulting quantity, never grow it.
    """
    from trading_desk.risk import MAX_POSITION_PCT

    side = side.upper()
    if side not in {"BUY", "SELL"}:
        raise ValueError("side must be BUY or SELL")
    if equity <= 0 or entry <= 0 or stop <= 0:
        raise ValueError("equity, entry, and stop must be positive")
    if side == "BUY" and stop >= entry:
        raise ValueError("BUY stop must be below entry")
    if side == "SELL" and stop <= entry:
        raise ValueError("SELL stop must be above entry")

    approved_pct = min(max(0.0, float(size_pct)), MAX_POSITION_PCT)
    risk_money = equity * approved_pct / 100.0
    fee_rate = max(0.0, float(fee_rate))
    risk_money *= max(0.0, 1.0 - fee_rate)
    if risk_money <= 0:
        raise ValueError("effective risk budget is zero")

    quantity = risk_money / abs(entry - stop)

    if step and step > 0:
        floored_steps = math.floor((quantity + 1e-12) / step)
        quantity = floored_steps * step

    if min_qty is not None and quantity < min_qty - 1e-12:
        raise ValueError(f"quantity {quantity:.8f} is below the exchange minimum quantity {min_qty}")

    if min_notional is not None and quantity * entry < min_notional - 1e-9:
        raise ValueError(
            f"notional {quantity * entry:.2f} is below the exchange minimum notional {min_notional}"
        )

    if quantity <= 0:
        raise ValueError("computed quantity is zero after applying exchange filters")

    return quantity


def paper_order(
    symbol: str, side: str, quantity: float, live: bool = False, size_pct: float | None = None
) -> dict[str, Any]:
    from trading_desk.operating_mode import require_paper_mode
    from trading_desk.risk import check_order, record_open

    require_paper_mode(live_requested=live)

    gate = check_order("binance", symbol, side, size_pct=size_pct)
    if not gate.approved:
        return {"status": "blocked", "reason": gate.reason, "venue": "binance", "symbol": symbol, "side": side.upper()}

    extra = [symbol, side.upper(), str(quantity)]
    if live:
        extra.append("--live")
    result = invoke("order", extra)
    if result.get("status") in {"paper-logged", "submitted"}:
        record_open("binance", symbol, side, size_pct=gate.size_pct if gate.size_pct is not None else size_pct)
    return result
