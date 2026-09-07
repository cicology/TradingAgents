"""TA-304: deterministic, evidence-based promotion gates.

Every gate names the metric it read, the threshold it applied, and why it
passed or failed, so a promotion decision can be audited rather than
trusted. Nothing here consumes an LLM opinion: the function signature has
no parameter through which a model's judgement could enter, which is how
Architectural Rule 3 ("deterministic code owns promotion decisions") is
enforced structurally rather than by convention. A model may summarize
this report; it cannot produce one.

**This module cannot award demo or live eligibility.** The highest state
reachable from metrics alone is `PAPER_QUALIFIED`. Demo and live require a
recorded human decision, an independent safety review, and a separate
release decision (mission Phase 7) — a function that could promote to live
from numbers alone would be the most dangerous code in the repository.

Gates fail closed: a missing, `None`, or unavailable input fails its gate
with an explicit reason. "We could not measure this" must never be
recorded as "this passed".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PromotionState(str, Enum):
    RESEARCH = "research"
    BACKTEST_PASSED = "backtest-passed"
    PAPER_QUALIFIED = "paper-qualified"
    # Reachable only via a recorded human decision, never by this module.
    DEMO_QUALIFIED = "demo-qualified"
    LIVE_ELIGIBLE = "live-eligible"


@dataclass(frozen=True)
class GateCriteria:
    """Thresholds from the 2026-09-02 evidence-first promotion decision
    (see docs/TRACKER.md Decision Log)."""

    min_trades: int = 100
    min_evidence_days: int = 90
    max_drawdown_pct: float = 20.0
    min_profitable_fold_ratio: float = 0.5


DEFAULT_CRITERIA = GateCriteria()


@dataclass(frozen=True)
class GateResult:
    name: str
    passed: bool
    source_metric: str
    threshold: str
    observed: str
    reason: str


@dataclass(frozen=True)
class PromotionReport:
    state: PromotionState
    all_passed: bool
    gates: list[GateResult] = field(default_factory=list)
    next_step_note: str = ""


def _missing(name: str, source_metric: str, threshold: str) -> GateResult:
    return GateResult(
        name=name,
        passed=False,
        source_metric=source_metric,
        threshold=threshold,
        observed="unavailable",
        reason=(
            f"{source_metric} was unavailable, so this gate could not be evaluated; "
            "an unmeasured gate fails closed rather than passing by default"
        ),
    )


def _numeric_gate(
    *, name: str, source_metric: str, value: Any, threshold: float, comparison: str, unit: str = ""
) -> GateResult:
    """comparison is '>=', '>' or '<=' applied as value <comparison> threshold."""
    threshold_text = f"{comparison} {threshold}{unit}"
    if value is None:
        return _missing(name, source_metric, threshold_text)

    if comparison == ">=":
        passed = value >= threshold
    elif comparison == ">":
        passed = value > threshold
    elif comparison == "<=":
        passed = value <= threshold
    else:  # pragma: no cover - guarded by callers in this module
        raise ValueError(f"unsupported comparison: {comparison}")

    verdict = "meets" if passed else "does not meet"
    # Round for readability in the rendered report, but only for display —
    # the pass/fail decision above used the exact value.
    shown = f"{value:.4g}{unit}" if isinstance(value, float) else f"{value}{unit}"
    return GateResult(
        name=name,
        passed=passed,
        source_metric=source_metric,
        threshold=threshold_text,
        observed=shown,
        reason=f"{source_metric} of {shown} {verdict} the required {threshold_text}",
    )


def evaluate_promotion(
    *,
    metrics: dict[str, Any],
    baseline_comparison: dict[str, Any] | None,
    evidence_days: float | None,
    safety_violation_count: int | None,
    profitable_fold_ratio: float | None,
    criteria: GateCriteria = DEFAULT_CRITERIA,
) -> PromotionReport:
    """Evaluate every promotion gate and derive the resulting state.

    Note the inputs: metrics, a baseline comparison, an evidence window, a
    safety-violation count, and walk-forward consistency. There is
    deliberately no parameter for a model's recommendation, a manual
    override, or a confidence score.
    """
    gates: list[GateResult] = [
        _numeric_gate(
            name="minimum_trades",
            source_metric="metrics.trade_count",
            value=metrics.get("trade_count"),
            threshold=criteria.min_trades,
            comparison=">=",
        ),
        _numeric_gate(
            name="minimum_evidence_days",
            source_metric="evidence_days",
            value=evidence_days,
            threshold=criteria.min_evidence_days,
            comparison=">=",
            unit=" days",
        ),
        _numeric_gate(
            name="positive_expectancy",
            source_metric="metrics.expectancy_pct",
            value=metrics.get("expectancy_pct"),
            threshold=0.0,
            comparison=">",
            unit="%",
        ),
        _numeric_gate(
            name="drawdown_within_limit",
            source_metric="metrics.max_drawdown_pct",
            value=metrics.get("max_drawdown_pct"),
            threshold=criteria.max_drawdown_pct,
            comparison="<=",
            unit="%",
        ),
        _numeric_gate(
            name="walk_forward_consistency",
            source_metric="profitable_fold_ratio",
            value=profitable_fold_ratio,
            threshold=criteria.min_profitable_fold_ratio,
            comparison=">=",
        ),
        _numeric_gate(
            name="no_safety_violations",
            source_metric="safety_violation_count",
            value=safety_violation_count,
            threshold=0,
            comparison="<=",
        ),
        _baseline_gate(baseline_comparison),
    ]

    all_passed = all(gate.passed for gate in gates)
    state = PromotionState.PAPER_QUALIFIED if all_passed else PromotionState.RESEARCH

    return PromotionReport(
        state=state,
        all_passed=all_passed,
        gates=gates,
        next_step_note=(
            "Demo and live eligibility are NOT granted by this report. They require a "
            "recorded human decision, an independent safety review, broker reconciliation, "
            "kill-switch drills, and a separate release decision."
        ),
    )


def _baseline_gate(comparison: dict[str, Any] | None) -> GateResult:
    threshold_text = "strategy return > baseline return"
    if comparison is None or not comparison.get("baseline_available"):
        return _missing("beats_baseline", "baseline_comparison.beats_baseline_return", threshold_text)

    beats = comparison.get("beats_baseline_return")
    if beats is None:
        return _missing("beats_baseline", "baseline_comparison.beats_baseline_return", threshold_text)

    delta = comparison.get("return_delta_pct")
    baseline_version = comparison.get("baseline_version", "unknown baseline")
    verdict = "beats" if beats else "does not beat"
    return GateResult(
        name="beats_baseline",
        passed=bool(beats),
        source_metric="baseline_comparison.beats_baseline_return",
        threshold=threshold_text,
        observed=f"{delta:+.2f}% vs {baseline_version}" if delta is not None else "unknown",
        reason=f"strategy {verdict} {baseline_version} by {delta:+.2f}% return"
        if delta is not None
        else f"strategy {verdict} {baseline_version}",
    )


def render_promotion_markdown(report: PromotionReport) -> str:
    lines = [
        "# Promotion gate report",
        "",
        f"**State:** `{report.state.value}` - {'all gates passed' if report.all_passed else 'blocked'}",
        "",
        "| Gate | Verdict | Source metric | Threshold | Observed | Reason |",
        "|---|---|---|---|---|---|",
    ]
    for gate in report.gates:
        verdict = "PASS" if gate.passed else "FAIL"
        lines.append(
            f"| {gate.name} | {verdict} | `{gate.source_metric}` | {gate.threshold} | {gate.observed} | {gate.reason} |"
        )
    lines += ["", f"> {report.next_step_note}"]
    return "\n".join(lines)
