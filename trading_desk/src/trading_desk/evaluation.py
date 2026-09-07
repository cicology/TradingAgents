"""TA-305: leakage-safe walk-forward evaluation runner.

Ties Phase 3 together: walk-forward folds (TA-303) -> per-fold strategy
replay -> metrics (TA-301) -> baseline comparison (TA-302) -> promotion
gates (TA-304), under an explicit, hashed configuration so a report can be
reproduced from `(bars, config)` alone.

**Honest scope note.** The current strategy (`strategy.ema_crossover_proposal`)
has no fitted parameters, so a fold's training window is used only as
indicator history, never to fit anything. Walk-forward here therefore
demonstrates *stability across time and regimes* — it does not yet
demonstrate protection against parameter overfitting, because there are no
parameters being selected. When a strategy with tunable parameters is
introduced, parameter selection must happen inside the training window
only, and this module will need a fitting hook that provably cannot see
the test window. Reading this report as "overfitting has been ruled out"
would be wrong today.

Decisions are made using only bars up to and including the decision bar;
fills and stop/target resolution use later bars *within the same fold's
test window*, and a position that cannot resolve inside that window is
dropped rather than resolved with data the fold should not see.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from trading_desk.baseline import buy_and_hold_outcome, compare_to_baseline
from trading_desk.domain import Action, MarketSnapshot, Outcome, ValidationError, Verdict
from trading_desk.lifecycle import replay_position
from trading_desk.market_data import Bar
from trading_desk.metrics import compute_metrics
from trading_desk.paper_broker import build_order_intent, simulate_fill
from trading_desk.promotion import PromotionReport, evaluate_promotion, render_promotion_markdown
from trading_desk.sizing import size_decision
from trading_desk.strategy import MIN_BARS, ema_crossover_proposal
from trading_desk.validation import validate_decision
from trading_desk.walk_forward import walk_forward_windows


@dataclass(frozen=True)
class EvaluationConfig:
    instrument: str
    venue: str
    symbol: str
    strategy_version: str
    horizon: str
    equity: float
    base_risk_pct: float
    spread: float
    slippage: float
    commission_per_unit: float
    max_holding_bars: int
    train_size: int
    test_size: int
    step: int


@dataclass(frozen=True)
class FoldReport:
    index: int
    test_start: datetime
    test_end: datetime
    outcomes: list[Outcome]
    metrics: dict[str, Any]


@dataclass(frozen=True)
class EvaluationReport:
    config_hash: str
    config: EvaluationConfig
    fold_count: int
    folds: list[FoldReport]
    metrics: dict[str, Any]
    baseline_metrics: dict[str, Any] | None
    baseline_comparison: dict[str, Any]
    profitable_fold_ratio: float | None
    promotion: PromotionReport
    evidence_days: float
    notes: list[str] = field(default_factory=list)


def config_hash(config: EvaluationConfig) -> str:
    """Stable hash of every assumption a run depends on. Two reports with
    the same hash were produced under identical costs, sizing and
    partitioning — change any of them and the hash changes."""
    canonical = json.dumps(asdict(config), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _replay_fold(history: list[Bar], test_bars: list[Bar], config: EvaluationConfig) -> list[Outcome]:
    """Walk the fold's test window, making a decision on each bar from
    history available *up to that bar only*, and resolving any resulting
    position within the remainder of the same window."""
    outcomes: list[Outcome] = []
    combined = history + test_bars
    offset = len(history)
    i = 0

    while i < len(test_bars):
        decision_index = offset + i
        visible = combined[: decision_index + 1]
        if len(visible) < MIN_BARS:
            i += 1
            continue

        proposal = ema_crossover_proposal(visible, strategy_version=config.strategy_version)
        decision_bar = combined[decision_index]
        market = MarketSnapshot(
            instrument=config.instrument, as_of=decision_bar.time, last_close=decision_bar.close
        )
        try:
            decision = validate_decision(
                proposal,
                instrument=config.instrument,
                strategy_version=config.strategy_version,
                market=market,
                horizon=config.horizon,
                now=decision_bar.time,
            )
        except ValidationError:
            i += 1
            continue

        sized = size_decision(decision, base_risk_pct=config.base_risk_pct)
        if sized.verdict is Verdict.REJECT or sized.action not in (Action.BUY, Action.SELL):
            i += 1
            continue

        # The fill happens on the next bar, and resolution may only use
        # bars still inside this fold's test window.
        remaining = test_bars[i + 1 :]
        if not remaining:
            break

        try:
            intent = build_order_intent(
                sized,
                venue=config.venue,
                symbol=config.symbol,
                equity=config.equity,
                decision_id=f"{config.strategy_version}:{decision_bar.time.isoformat()}",
            )
        except ValidationError:
            i += 1
            continue

        entry = simulate_fill(
            intent,
            remaining[0],
            spread=config.spread,
            slippage=config.slippage,
            commission_per_unit=config.commission_per_unit,
        )
        replay = replay_position(
            intent,
            entry,
            remaining,
            equity=config.equity,
            commission_per_unit=config.commission_per_unit,
            max_holding_bars=config.max_holding_bars,
        )
        outcomes.append(replay.outcome)

        # Advance past the closed position: one position per symbol at a
        # time, mirroring the shared risk gate's duplicate-position rule.
        closed_at = replay.outcome.closed_at
        while i < len(test_bars) and test_bars[i].time <= closed_at:
            i += 1

    return outcomes


def run_evaluation(bars: list[Bar], config: EvaluationConfig) -> EvaluationReport:
    notes = [
        "Walk-forward here demonstrates stability across time, not protection against "
        "parameter overfitting: the current strategy has no fitted parameters.",
    ]

    folds_raw = (
        walk_forward_windows(bars, train_size=config.train_size, test_size=config.test_size, step=config.step)
        if bars
        else []
    )

    fold_reports: list[FoldReport] = []
    all_outcomes: list[Outcome] = []
    for fold in folds_raw:
        outcomes = _replay_fold(fold.train, fold.test, config)
        all_outcomes.extend(outcomes)
        fold_reports.append(
            FoldReport(
                index=fold.index,
                test_start=fold.test[0].time,
                test_end=fold.test[-1].time,
                outcomes=outcomes,
                metrics=compute_metrics(outcomes),
            )
        )

    metrics = compute_metrics(all_outcomes)

    evaluated_folds = [f for f in fold_reports if f.outcomes]
    profitable_fold_ratio = (
        sum(1 for f in evaluated_folds if f.metrics["total_return_pct"] > 0) / len(evaluated_folds)
        if evaluated_folds
        else None
    )
    if not evaluated_folds:
        notes.append("No fold produced a trade, so walk-forward consistency could not be measured.")

    # Baseline over the same span the strategy was evaluated on, sized so a
    # one-unit move is comparable, and paying the same costs.
    baseline_outcome = (
        buy_and_hold_outcome(
            bars,
            instrument=config.instrument,
            venue=config.venue,
            symbol=config.symbol,
            equity=config.equity,
            quantity=config.equity * config.base_risk_pct / 100.0,
            spread=config.spread,
            slippage=config.slippage,
            commission_per_unit=config.commission_per_unit,
        )
        if bars
        else None
    )
    baseline_metrics = compute_metrics([baseline_outcome]) if baseline_outcome else None
    baseline_comparison = compare_to_baseline(metrics, baseline_metrics)

    evidence_days = ((bars[-1].time - bars[0].time).total_seconds() / 86400.0) if len(bars) > 1 else 0.0

    promotion = evaluate_promotion(
        metrics=metrics,
        baseline_comparison=baseline_comparison,
        evidence_days=evidence_days,
        safety_violation_count=0,
        profitable_fold_ratio=profitable_fold_ratio,
    )

    return EvaluationReport(
        config_hash=config_hash(config),
        config=config,
        fold_count=len(fold_reports),
        folds=fold_reports,
        metrics=metrics,
        baseline_metrics=baseline_metrics,
        baseline_comparison=baseline_comparison,
        profitable_fold_ratio=profitable_fold_ratio,
        promotion=promotion,
        evidence_days=evidence_days,
        notes=notes,
    )


def _fmt(value: Any, digits: int = 2) -> str:
    """Format a number for an operator, not a debugger. `None` renders as
    'n/a' rather than the string 'None', which reads like a bug."""
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def render_evaluation_markdown(report: EvaluationReport) -> str:
    m = report.metrics
    lines = [
        f"# Evaluation report - {report.config.strategy_version}",
        "",
        f"- Config hash: `{report.config_hash[:12]}`",
        f"- Instrument / horizon: {report.config.instrument} / {report.config.horizon}",
        f"- Evidence window: {report.evidence_days:.1f} days",
        f"- Costs: spread {report.config.spread}, slippage {report.config.slippage}, "
        f"commission/unit {report.config.commission_per_unit}",
        "",
        "## Aggregate",
        "",
        f"- Trades: {m['trade_count']}",
        f"- Total return: {m['total_return_pct']:.2f}%",
        f"- Max drawdown: {m['max_drawdown_pct']:.2f}%",
        f"- Worst trade: {_fmt(m['worst_trade_pct'])}",
        f"- Longest losing streak: {m['longest_losing_streak']}",
        "",
        "## Walk-forward folds",
        "",
        "| Fold | Window | Trades | Return % | Max DD % |",
        "|---:|---|---:|---:|---:|",
    ]
    for fold in report.folds:
        fm = fold.metrics
        lines.append(
            f"| {fold.index} | {fold.test_start.date()} -> {fold.test_end.date()} | "
            f"{fm['trade_count']} | {fm['total_return_pct']:.2f} | {fm['max_drawdown_pct']:.2f} |"
        )
    ratio = report.profitable_fold_ratio
    lines += [
        "",
        f"Profitable folds: {ratio if ratio is None else f'{ratio:.0%}'}",
        "",
        render_promotion_markdown(report.promotion),
        "",
        "## Notes",
        "",
    ]
    lines += [f"- {note}" for note in report.notes]
    return "\n".join(lines)


def save_evaluation_artifacts(report: EvaluationReport, directory: Path | str) -> dict[str, Path]:
    """Write the report as both machine-readable JSON and an operator-
    readable Markdown summary, named by config hash so two runs under
    different assumptions can never overwrite each other.

    Always written UTF-8 explicitly: Windows' default console/file encoding
    is cp1252 and would mangle or refuse non-ASCII content.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stem = f"evaluation_{report.config.strategy_version.replace('@', '_')}_{report.config_hash[:12]}"

    json_path = directory / f"{stem}.json"
    markdown_path = directory / f"{stem}.md"

    payload = {
        "config_hash": report.config_hash,
        "config": asdict(report.config),
        "evidence_days": report.evidence_days,
        "fold_count": report.fold_count,
        "profitable_fold_ratio": report.profitable_fold_ratio,
        "metrics": report.metrics,
        "baseline_metrics": report.baseline_metrics,
        "baseline_comparison": report.baseline_comparison,
        "folds": [
            {
                "index": fold.index,
                "test_start": fold.test_start.isoformat(),
                "test_end": fold.test_end.isoformat(),
                "trade_count": len(fold.outcomes),
                "metrics": fold.metrics,
            }
            for fold in report.folds
        ],
        "promotion": {
            "state": report.promotion.state.value,
            "all_passed": report.promotion.all_passed,
            "next_step_note": report.promotion.next_step_note,
            "gates": [asdict(gate) for gate in report.promotion.gates],
        },
        "notes": report.notes,
    }

    json_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    markdown_path.write_text(render_evaluation_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
