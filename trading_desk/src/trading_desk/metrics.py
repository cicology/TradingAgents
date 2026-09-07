"""TA-301: net performance and risk metrics.

Computed from closed `Outcome` records whose `realized_pnl_pct` is already
net of the transaction costs applied at fill and close time (see
`paper_broker.simulate_fill` and `lifecycle.replay_position`) — there is
no separate "gross" mode here, because a gross number is not evidence of
anything the desk can act on.

Deliberately reports drawdown, tail risk, and losing streaks alongside
return and dispersion: no single headline number is sufficient evidence
for promotion (see `promotion.py`). Where a statistic is genuinely
undefined for the sample (profit factor with no losses, dispersion from a
single trade), this returns `None` rather than infinity, zero, or a
fabricated value that would read as real evidence downstream.
"""

from __future__ import annotations

import math
from typing import Any

from trading_desk.domain import Outcome


def _equity_curve(pnls: list[float]) -> list[float]:
    curve: list[float] = []
    running = 0.0
    for pnl in pnls:
        running += pnl
        curve.append(running)
    return curve


def _max_drawdown(curve: list[float]) -> float:
    """Largest peak-to-trough decline on the cumulative curve. A curve that
    never declines has a drawdown of 0.0, and the peak starts at 0 (flat,
    pre-first-trade equity) so an immediately losing series is measured
    from that flat start rather than from its own first loss."""
    if not curve:
        return 0.0
    peak = 0.0
    max_dd = 0.0
    for value in curve:
        peak = max(peak, value)
        max_dd = max(max_dd, peak - value)
    return max_dd


def _longest_losing_streak(pnls: list[float]) -> int:
    longest = 0
    current = 0
    for pnl in pnls:
        if pnl <= 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _sample_stdev(values: list[float]) -> float | None:
    """Sample standard deviation (n-1). None for fewer than two values —
    a single trade has no measurable dispersion."""
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance)


def _worst_decile_mean(pnls: list[float]) -> float | None:
    """Mean of the worst 10% of trades (at least one), a simple CVaR-style
    tail statistic. None for an empty sample."""
    if not pnls:
        return None
    count = max(1, len(pnls) // 10)
    worst = sorted(pnls)[:count]
    return sum(worst) / len(worst)


def compute_metrics(outcomes: list[Outcome]) -> dict[str, Any]:
    pnls = [o.realized_pnl_pct for o in outcomes]
    trade_count = len(pnls)

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_profit = sum(wins)
    gross_loss = -sum(losses)  # positive magnitude

    curve = _equity_curve(pnls)
    stdev = _sample_stdev(pnls)
    total_return = sum(pnls)

    return {
        "trade_count": trade_count,
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate": (len(wins) / trade_count) if trade_count else None,
        "total_return_pct": total_return,
        "expectancy_pct": (total_return / trade_count) if trade_count else None,
        "gross_profit_pct": gross_profit,
        "gross_loss_pct": gross_loss,
        # Undefined without both sides — never inf, never a silent 0.
        "profit_factor": (gross_profit / gross_loss) if (wins and losses and gross_loss > 0) else None,
        "avg_win_pct": (gross_profit / len(wins)) if wins else None,
        "avg_loss_pct": (sum(losses) / len(losses)) if losses else None,
        "max_drawdown_pct": _max_drawdown(curve),
        "worst_trade_pct": min(pnls) if pnls else None,
        "worst_decile_mean_pct": _worst_decile_mean(pnls),
        "longest_losing_streak": _longest_losing_streak(pnls),
        "return_stdev_pct": stdev,
        # A dispersion-scaled return, NOT an annualized Sharpe ratio: these
        # are per-trade returns with no risk-free rate and no time
        # normalization. Named to avoid implying more than it measures.
        "return_over_stdev": ((total_return / trade_count) / stdev) if (stdev and stdev > 0) else None,
        "equity_curve_pct": curve,
    }
