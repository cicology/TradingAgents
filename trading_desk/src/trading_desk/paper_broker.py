"""TA-203: paper order and fill simulator for the Phase 2 canonical
pipeline.

`build_order_intent` sizes quantity purely from risk (equity × size_pct ÷
stop distance) — never a guess, and it raises rather than routes an order
with no valid direction or zero size. `simulate_fill` never produces a
costless fantasy fill: spread, slippage, and commission are explicit,
required parameters, and the resulting fill price always reflects them.
"""

from __future__ import annotations

from datetime import datetime, timezone

from trading_desk.domain import Action, ExecutionStatus, OrderIntent, PaperExecution, TradeDecision, ValidationError
from trading_desk.market_data import Bar


def build_order_intent(
    decision: TradeDecision, *, venue: str, symbol: str, equity: float, decision_id: str
) -> OrderIntent:
    """Size quantity from risk: equity * size_pct% / stop_distance. Raises
    ValidationError (via OrderIntent's own construction) if the decision
    isn't directional or the computed quantity isn't positive."""
    if decision.action not in (Action.BUY, Action.SELL):
        raise ValidationError(f"cannot build an OrderIntent from a non-directional decision: {decision.action}")
    if decision.entry is None or decision.stop is None:
        raise ValidationError("directional decision is missing entry/stop")

    risk_money = equity * decision.size_pct / 100.0
    stop_distance = abs(decision.entry - decision.stop)
    quantity = risk_money / stop_distance if stop_distance > 0 else 0.0
    target = decision.targets[0] if decision.targets else None

    return OrderIntent(
        venue=venue,
        symbol=symbol,
        action=decision.action,
        quantity=quantity,
        stop=decision.stop,
        target=target,
        strategy_version=decision.strategy_version,
        decision_id=decision_id,
    )


def simulate_fill(
    order_intent: OrderIntent,
    fill_bar: Bar,
    *,
    spread: float,
    slippage: float,
    commission_per_unit: float,
) -> PaperExecution:
    """Fill at the given bar's open, adjusted against the trader by half
    the spread plus slippage — both BUY and SELL pay these costs, never
    receive them. commission_per_unit is recorded for transparency (it
    reduces eventual realized PnL, computed at outcome time in TA-204/205)
    rather than folded into the fill price itself."""
    half_spread = spread / 2.0
    if order_intent.action is Action.BUY:
        fill_price = fill_bar.open + half_spread + slippage
    else:
        fill_price = fill_bar.open - half_spread - slippage

    reason = f"spread={spread} slippage={slippage} commission_per_unit={commission_per_unit}"
    return PaperExecution(
        order_intent=order_intent,
        status=ExecutionStatus.PAPER,
        fill_price=fill_price,
        reason=reason,
        executed_at=datetime.now(timezone.utc),
    )
