"""Shared risk gate, applied the same way across every venue (Binance, MT5,
and whatever comes next). This is the desk's version of the risk_manager
module from the original platform spec: every order — paper or live —
passes through here before it reaches an exchange connector.

Three checks, in order:
1. Daily loss halt — if today's realized PnL has breached MAX_DAILY_LOSS_PCT,
   nothing new gets approved until the day rolls over.
2. Duplicate-position prevention — don't re-enter a position already open
   on the same venue+symbol+side.
3. Max position size — clip size_pct to MAX_POSITION_PCT regardless of what
   Kelly or a manual order requested.

State is a small JSON file next to the reports directory. This is a CLI
tool invoked per-run, not a long-lived daemon, so state has to be on disk
to persist across invocations.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from trading_desk import ledger
from trading_desk.config import REPORTS_DIR
from trading_desk.domain import LifecycleEvent, LifecycleEventType

STATE_PATH: Path = REPORTS_DIR / "risk_state.json"
LEDGER_DB_PATH: Path = ledger.DEFAULT_DB_PATH

MAX_POSITION_PCT = float(os.getenv("MAX_POSITION_PCT", "5") or 5)
MAX_DAILY_LOSS_PCT = float(os.getenv("MAX_DAILY_LOSS_PCT", "2") or 2)


def _record_lifecycle_event(event_type: LifecycleEventType, venue: str, symbol: str, payload: dict[str, Any]) -> None:
    """Best-effort write into the immutable ledger (TA-105). This is an
    audit/provenance side-channel, not the safety-critical state itself —
    a disk/permission failure here must never block or corrupt the
    JSON risk-state gate that check_order()/record_open()/record_close()
    enforce. event_id is a fresh UUID per call: true retry-idempotency
    (deduplicating a genuinely repeated submission) needs a caller-
    supplied order/decision id, which arrives with the paper order/fill
    simulator (TA-203) — this only guarantees every real lifecycle
    transition is captured, not deduplicated across process retries."""
    try:
        conn = ledger.connect(LEDGER_DB_PATH)
    except Exception:
        return
    try:
        event = LifecycleEvent(
            event_id=str(uuid.uuid4()),
            venue=venue,
            symbol=symbol,
            event_type=event_type,
            occurred_at=datetime.now(timezone.utc),
            payload=payload,
        )
        ledger.record_lifecycle_event(conn, event)
    except Exception:
        pass
    finally:
        conn.close()


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reason: str
    size_pct: float | None


def _load_state() -> dict[str, Any]:
    if STATE_PATH.is_file():
        try:
            return json.loads(STATE_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"open_positions": {}, "daily": {}}


def _save_state(state: dict[str, Any]) -> None:
    """Write state via a same-directory temp file + atomic replace, so a
    crash mid-write can never leave a truncated/corrupt risk_state.json for
    the next run to load."""
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    temporary.replace(STATE_PATH)


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _position_key(venue: str, symbol: str) -> str:
    return f"{venue}:{symbol}".upper()


def daily_loss_breached() -> tuple[bool, float]:
    """Check today's realized PnL against MAX_DAILY_LOSS_PCT.

    Resets automatically when the UTC date rolls over — no stale halt
    carrying into a new trading day.
    """
    state = _load_state()
    day = state.get("daily", {})
    if day.get("date") != _today():
        return False, 0.0
    pnl_pct = float(day.get("realized_pnl_pct", 0.0))
    return pnl_pct <= -MAX_DAILY_LOSS_PCT, pnl_pct


def check_order(venue: str, symbol: str, action: str, size_pct: float | None = None) -> RiskDecision:
    """Gate an order before it reaches an exchange connector.

    @param venue: 'binance', 'mt5', etc. — keeps position tracking separate
        per venue even for the same symbol name.
    @param symbol: exchange-native symbol, e.g. 'BTCUSDT', 'XAUUSD'.
    @param action: 'BUY' or 'SELL'. Anything else passes through unchecked
        (HOLD has nothing to gate).
    @param size_pct: requested position size as % of capital, if known.
        Clipped to MAX_POSITION_PCT; omitted (None) for manual orders where
        no % sizing was computed (duplicate/daily-loss checks still apply).
    """
    action = (action or "").upper()
    if action not in {"BUY", "SELL"}:
        return RiskDecision(True, "not a directional order", size_pct)

    breached, pnl_pct = daily_loss_breached()
    if breached:
        return RiskDecision(
            False, f"Daily loss halt: {pnl_pct:.2f}% (limit {MAX_DAILY_LOSS_PCT}%). Resets next UTC day.", 0.0
        )

    state = _load_state()
    key = _position_key(venue, symbol)
    existing = state.get("open_positions", {}).get(key)
    if existing:
        # Any existing position blocks a new entry on this venue+symbol —
        # not just a same-side duplicate. A same-key opposite-side order
        # would otherwise overwrite the tracked position in record_open's
        # dict assignment, silently losing the original position from risk
        # state (the position it represents is still open at the broker).
        return RiskDecision(
            False,
            f"Position already open on {venue}:{symbol} "
            f"({existing.get('side')} since {existing.get('opened_at')}); close it before opening another.",
            0.0,
        )

    capped = size_pct
    if size_pct is not None and size_pct > MAX_POSITION_PCT:
        capped = MAX_POSITION_PCT

    return RiskDecision(True, "approved", capped)


def record_open(venue: str, symbol: str, action: str, size_pct: float | None = None) -> None:
    """Mark a position as open after an order actually goes through
    (paper-logged counts — it should still block a duplicate paper entry).

    @param size_pct: the approved position size, persisted so a restart can
        reconcile risk state without re-deriving it.
    """
    action = (action or "").upper()
    if action not in {"BUY", "SELL"}:
        return
    state = _load_state()
    state.setdefault("open_positions", {})[_position_key(venue, symbol)] = {
        "side": action,
        "size_pct": size_pct,
        "opened_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_state(state)
    _record_lifecycle_event(LifecycleEventType.OPEN, venue, symbol, {"side": action, "size_pct": size_pct})


def record_close(venue: str, symbol: str, realized_pnl_pct: float = 0.0) -> None:
    """Clear a position and roll its realized PnL into today's total."""
    state = _load_state()
    key = _position_key(venue, symbol)
    state.get("open_positions", {}).pop(key, None)
    day = state.setdefault("daily", {})
    if day.get("date") != _today():
        day["date"] = _today()
        day["realized_pnl_pct"] = 0.0
    day["realized_pnl_pct"] = float(day.get("realized_pnl_pct", 0.0)) + realized_pnl_pct
    _save_state(state)
    _record_lifecycle_event(LifecycleEventType.CLOSE, venue, symbol, {"realized_pnl_pct": realized_pnl_pct})


def open_positions() -> dict[str, Any]:
    return _load_state().get("open_positions", {})


def reset_daily() -> None:
    """Clear today's realized PnL, lifting a daily-loss halt early. Open
    positions are untouched — this only resets the loss counter."""
    state = _load_state()
    state["daily"] = {"date": _today(), "realized_pnl_pct": 0.0}
    _save_state(state)
