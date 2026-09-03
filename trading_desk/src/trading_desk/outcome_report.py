"""TA-205: operator-readable outcome report.

`build_report` is a pure derived view over `ledger.list_outcomes()` — it
never maintains its own totals or state, so its numbers can never drift
from what a direct ledger query returns. `render_report_markdown` turns
that into something an operator can read without querying SQL directly.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from trading_desk import ledger


def build_report(conn: sqlite3.Connection, *, strategy_version: str) -> dict[str, Any]:
    outcomes = ledger.list_outcomes(conn, strategy_version=strategy_version)
    trade_count = len(outcomes)
    win_count = sum(1 for o in outcomes if o.realized_pnl_pct > 0)
    loss_count = sum(1 for o in outcomes if o.realized_pnl_pct <= 0)
    total_realized_pnl_pct = sum(o.realized_pnl_pct for o in outcomes)

    equity_curve_pct: list[float] = []
    running = 0.0
    for outcome in outcomes:
        running += outcome.realized_pnl_pct
        equity_curve_pct.append(running)

    return {
        "strategy_version": strategy_version,
        "trade_count": trade_count,
        "win_count": win_count,
        "loss_count": loss_count,
        "win_rate": (win_count / trade_count) if trade_count else None,
        "total_realized_pnl_pct": total_realized_pnl_pct,
        "equity_curve_pct": equity_curve_pct,
        "first_closed_at": outcomes[0].closed_at.isoformat() if outcomes else None,
        "last_closed_at": outcomes[-1].closed_at.isoformat() if outcomes else None,
    }


def render_report_markdown(report: dict[str, Any]) -> str:
    win_rate = report["win_rate"]
    win_rate_text = f"{win_rate:.1%}" if win_rate is not None else "n/a"
    lines = [
        f"# Outcome report — {report['strategy_version']}",
        "",
        f"- Trades: {report['trade_count']} ({report['win_count']} win / {report['loss_count']} loss)",
        f"- Win rate: {win_rate_text}",
        f"- Total realized PnL: {report['total_realized_pnl_pct']:.2f}%",
        f"- Window: {report['first_closed_at'] or 'n/a'} — {report['last_closed_at'] or 'n/a'}",
        "",
        "This is a raw outcome tally, not a promotion decision — see Phase 3's",
        "evaluation framework (walk-forward, baselines, drawdown) before treating",
        "any of these numbers as evidence of an edge.",
    ]
    return "\n".join(lines)
