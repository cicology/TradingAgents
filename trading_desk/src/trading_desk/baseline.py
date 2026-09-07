"""TA-302: deterministic, versioned non-AI baseline.

A strategy that cannot beat buy-and-hold over the same bars, paying the
same transaction costs, has not demonstrated an edge — it has
demonstrated exposure. This module exists so a promotion report can name
exactly which baseline a candidate was measured against, and reproduce it.

The baseline deliberately pays the same spread, slippage, and round-trip
commission as the strategy. A costless baseline would be an unfairly easy
target, which would flatter every candidate compared against it.
"""

from __future__ import annotations

from typing import Any

from trading_desk.domain import Outcome
from trading_desk.market_data import Bar

BASELINE_VERSION = "buy-and-hold@1"


def buy_and_hold_outcome(
    bars: list[Bar],
    *,
    instrument: str,
    venue: str,
    symbol: str,
    equity: float,
    quantity: float,
    spread: float,
    slippage: float,
    commission_per_unit: float,
) -> Outcome | None:
    """Buy at the first bar's open, hold to the last bar's close.

    Returns None for fewer than two bars — a window with no holding period
    has no baseline, and reporting 0.0% there would falsely read as "the
    baseline made nothing" rather than "there was no baseline".
    """
    if len(bars) < 2:
        return None

    first, last = bars[0], bars[-1]
    # Entry pays half the spread plus slippage, same as paper_broker's BUY.
    entry_price = first.open + (spread / 2.0) + slippage
    # Exit pays them too, in the other direction.
    exit_price = last.close - (spread / 2.0) - slippage

    gross_pnl = (exit_price - entry_price) * quantity
    commission_cost = commission_per_unit * quantity * 2  # entry + exit
    net_pnl = gross_pnl - commission_cost
    realized_pnl_pct = (net_pnl / equity) * 100.0 if equity else 0.0

    return Outcome(
        venue=venue,
        symbol=symbol,
        strategy_version=BASELINE_VERSION,
        opened_at=first.time,
        closed_at=last.time,
        realized_pnl_pct=realized_pnl_pct,
    )


def compare_to_baseline(
    strategy_metrics: dict[str, Any], baseline_metrics: dict[str, Any] | None
) -> dict[str, Any]:
    """Compare a candidate's metrics against the baseline's.

    When there is no baseline, the `beats_*` flags are None — "not
    compared" must never be readable as "passed" by a downstream
    promotion gate.
    """
    if baseline_metrics is None:
        return {
            "baseline_version": BASELINE_VERSION,
            "baseline_available": False,
            "return_delta_pct": None,
            "drawdown_delta_pct": None,
            "beats_baseline_return": None,
            "beats_baseline_drawdown": None,
        }

    return_delta = strategy_metrics["total_return_pct"] - baseline_metrics["total_return_pct"]
    # Negative delta is good here: a smaller drawdown than the baseline.
    drawdown_delta = strategy_metrics["max_drawdown_pct"] - baseline_metrics["max_drawdown_pct"]

    return {
        "baseline_version": BASELINE_VERSION,
        "baseline_available": True,
        "return_delta_pct": return_delta,
        "drawdown_delta_pct": drawdown_delta,
        "beats_baseline_return": return_delta > 0,
        "beats_baseline_drawdown": drawdown_delta < 0,
    }
