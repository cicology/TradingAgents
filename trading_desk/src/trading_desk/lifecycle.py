"""TA-204: position lifecycle replay — stop, target, and expiry.

`replay_position` walks the bars following an entry fill and decides,
conservatively, what closed the position: a stop-loss, a take-profit
target, or expiry (holding-period limit reached with neither hit). When a
single bar's range could contain both the stop and the target, the true
intrabar order is unknowable from OHLC data alone — this always resolves
to the worse outcome (stop) rather than assuming the favorable order,
matching standard backtesting practice against optimistic bias.
"""

from __future__ import annotations

from dataclasses import dataclass

from trading_desk.domain import Action, OrderIntent, Outcome, PaperExecution, ValidationError
from trading_desk.market_data import Bar


@dataclass(frozen=True)
class ReplayResult:
    outcome: Outcome
    exit_reason: str
    exit_price: float

    def __iter__(self):
        # Allows `outcome, reason = replay_position(...)` at call sites
        # that only need those two, while still exposing exit_price.
        yield self.outcome
        yield self.exit_reason


def _level_hit(intent: OrderIntent, bar: Bar) -> tuple[bool, bool]:
    """Return (stop_hit, target_hit) for this bar, direction-aware."""
    if intent.action is Action.BUY:
        stop_hit = bar.low <= intent.stop
        target_hit = intent.target is not None and bar.high >= intent.target
    else:
        stop_hit = bar.high >= intent.stop
        target_hit = intent.target is not None and bar.low <= intent.target
    return stop_hit, target_hit


def replay_position(
    order_intent: OrderIntent,
    entry_execution: PaperExecution,
    subsequent_bars: list[Bar],
    *,
    equity: float,
    commission_per_unit: float,
    max_holding_bars: int,
) -> ReplayResult:
    if not subsequent_bars:
        raise ValidationError("replay_position requires at least one subsequent bar")
    if order_intent.stop is None:
        raise ValidationError("order_intent is missing a stop; cannot replay a position without one")

    direction = 1 if order_intent.action is Action.BUY else -1
    entry_price = entry_execution.fill_price
    opened_at = entry_execution.executed_at

    window = subsequent_bars[:max_holding_bars]
    exit_price: float | None = None
    exit_time = None
    reason: str | None = None

    for bar in window:
        stop_hit, target_hit = _level_hit(order_intent, bar)
        if stop_hit:
            exit_price = order_intent.stop
            exit_time = bar.time
            reason = "stop_hit"
            break
        if target_hit:
            exit_price = order_intent.target
            exit_time = bar.time
            reason = "target_hit"
            break

    if reason is None:
        last_bar = window[-1]
        exit_price = last_bar.close
        exit_time = last_bar.time
        reason = "expiry"

    gross_pnl = direction * (exit_price - entry_price) * order_intent.quantity
    commission_cost = commission_per_unit * order_intent.quantity * 2  # entry + exit
    net_pnl = gross_pnl - commission_cost
    realized_pnl_pct = (net_pnl / equity) * 100.0 if equity else 0.0

    outcome = Outcome(
        venue=order_intent.venue,
        symbol=order_intent.symbol,
        strategy_version=order_intent.strategy_version,
        opened_at=opened_at,
        closed_at=exit_time,
        realized_pnl_pct=realized_pnl_pct,
    )
    return ReplayResult(outcome=outcome, exit_reason=reason, exit_price=exit_price)
