"""TA-304: the promotion gate report.

Two properties matter more than any individual threshold here:

1. Promotion is deterministic and evidence-based. Every gate names the
   metric it read, the threshold it applied, and why it passed or failed.
2. This code cannot award demo/live eligibility. The highest state it can
   reach on its own is paper-qualified; demo and live require a recorded
   human decision (mission Phase 7). A function that could promote to live
   from metrics alone would be the single most dangerous thing in the repo.
"""

from __future__ import annotations

import pytest

from trading_desk.promotion import (
    DEFAULT_CRITERIA,
    PromotionState,
    evaluate_promotion,
)


def passing_metrics() -> dict:
    return {
        "trade_count": 120,
        "total_return_pct": 8.0,
        "expectancy_pct": 0.067,
        "max_drawdown_pct": 4.0,
        "profit_factor": 1.6,
        "win_rate": 0.55,
        "worst_decile_mean_pct": -1.2,
    }


def passing_comparison() -> dict:
    return {
        "baseline_version": "buy-and-hold@1",
        "baseline_available": True,
        "return_delta_pct": 3.0,
        "drawdown_delta_pct": -1.0,
        "beats_baseline_return": True,
        "beats_baseline_drawdown": True,
    }


def evaluate(**overrides):
    kwargs = dict(
        metrics=passing_metrics(),
        baseline_comparison=passing_comparison(),
        evidence_days=120,
        safety_violation_count=0,
        profitable_fold_ratio=0.7,
    )
    kwargs.update(overrides)
    return evaluate_promotion(**kwargs)


# ---------------------------------------------------------------------------
# The ceiling: this code cannot promote to demo or live
# ---------------------------------------------------------------------------


def test_a_fully_passing_candidate_reaches_paper_qualified_and_no_further() -> None:
    report = evaluate()
    assert report.all_passed is True
    assert report.state is PromotionState.PAPER_QUALIFIED


def test_no_input_can_produce_demo_or_live_eligibility() -> None:
    """Even absurdly good numbers must not reach demo/live: those require
    a recorded human decision outside this function."""
    stellar = passing_metrics() | {
        "trade_count": 100_000,
        "total_return_pct": 5000.0,
        "max_drawdown_pct": 0.01,
        "profit_factor": 99.0,
    }
    report = evaluate(metrics=stellar, evidence_days=10_000, profitable_fold_ratio=1.0)
    assert report.state is PromotionState.PAPER_QUALIFIED
    assert report.state not in (PromotionState.DEMO_QUALIFIED, PromotionState.LIVE_ELIGIBLE)


def test_report_states_that_demo_and_live_need_a_human_decision() -> None:
    assert "human" in evaluate().next_step_note.lower()


# ---------------------------------------------------------------------------
# Every gate names its metric, threshold, and reason
# ---------------------------------------------------------------------------


def test_every_gate_records_its_source_metric_threshold_and_reason() -> None:
    for gate in evaluate().gates:
        assert gate.name
        assert gate.source_metric
        assert gate.reason
        assert isinstance(gate.passed, bool)


def test_failing_gate_reason_explains_the_shortfall() -> None:
    report = evaluate(metrics=passing_metrics() | {"trade_count": 12})
    gate = next(g for g in report.gates if g.name == "minimum_trades")
    assert gate.passed is False
    assert "12" in gate.reason
    assert str(DEFAULT_CRITERIA.min_trades) in gate.reason


# ---------------------------------------------------------------------------
# Individual gates
# ---------------------------------------------------------------------------


def test_insufficient_trades_blocks_promotion() -> None:
    report = evaluate(metrics=passing_metrics() | {"trade_count": 50})
    assert report.all_passed is False
    assert report.state is PromotionState.RESEARCH


def test_insufficient_evidence_days_blocks_promotion() -> None:
    report = evaluate(evidence_days=30)
    assert report.all_passed is False
    assert any(g.name == "minimum_evidence_days" and not g.passed for g in report.gates)


def test_negative_expectancy_blocks_promotion() -> None:
    report = evaluate(metrics=passing_metrics() | {"expectancy_pct": -0.2, "total_return_pct": -5.0})
    assert report.all_passed is False
    assert any(g.name == "positive_expectancy" and not g.passed for g in report.gates)


def test_excessive_drawdown_blocks_promotion() -> None:
    report = evaluate(metrics=passing_metrics() | {"max_drawdown_pct": 40.0})
    assert report.all_passed is False
    assert any(g.name == "drawdown_within_limit" and not g.passed for g in report.gates)


def test_losing_to_the_baseline_blocks_promotion() -> None:
    report = evaluate(baseline_comparison=passing_comparison() | {"beats_baseline_return": False})
    assert report.all_passed is False
    assert any(g.name == "beats_baseline" and not g.passed for g in report.gates)


def test_any_safety_violation_blocks_promotion() -> None:
    report = evaluate(safety_violation_count=1)
    assert report.all_passed is False
    assert any(g.name == "no_safety_violations" and not g.passed for g in report.gates)


def test_inconsistent_walk_forward_folds_block_promotion() -> None:
    """One lucky fold is not an edge. A majority of folds must be
    profitable, or the result is a single-window artifact."""
    report = evaluate(profitable_fold_ratio=0.2)
    assert report.all_passed is False
    assert any(g.name == "walk_forward_consistency" and not g.passed for g in report.gates)


# ---------------------------------------------------------------------------
# Fail closed on missing / unknown evidence
# ---------------------------------------------------------------------------


def test_missing_metric_fails_the_gate_rather_than_skipping_it() -> None:
    report = evaluate(metrics=passing_metrics() | {"max_drawdown_pct": None})
    gate = next(g for g in report.gates if g.name == "drawdown_within_limit")
    assert gate.passed is False
    assert "unavailable" in gate.reason.lower() or "missing" in gate.reason.lower()


def test_unavailable_baseline_fails_the_gate_rather_than_passing_it() -> None:
    no_baseline = {
        "baseline_version": "buy-and-hold@1",
        "baseline_available": False,
        "return_delta_pct": None,
        "drawdown_delta_pct": None,
        "beats_baseline_return": None,
        "beats_baseline_drawdown": None,
    }
    report = evaluate(baseline_comparison=no_baseline)
    gate = next(g for g in report.gates if g.name == "beats_baseline")
    assert gate.passed is False
    assert report.all_passed is False


def test_unknown_fold_ratio_fails_closed() -> None:
    report = evaluate(profitable_fold_ratio=None)
    assert any(g.name == "walk_forward_consistency" and not g.passed for g in report.gates)


# ---------------------------------------------------------------------------
# Determinism and rendering
# ---------------------------------------------------------------------------


def test_promotion_evaluation_is_deterministic() -> None:
    assert evaluate() == evaluate()


def test_markdown_report_lists_every_gate_with_its_verdict() -> None:
    from trading_desk.promotion import render_promotion_markdown

    report = evaluate(metrics=passing_metrics() | {"trade_count": 12})
    text = render_promotion_markdown(report)
    for gate in report.gates:
        assert gate.name in text
    assert "PASS" in text and "FAIL" in text
