"""TA-305: the evaluation runner ties TA-301-304 into one leakage-safe
walk-forward report — the mission's E2 exit criterion.

Tests assert structural properties (determinism, config hashing, no
lookahead, promotion wiring) rather than specific PnL values: pinning a
synthetic series' exact return would test the fixture, not the runner.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from trading_desk.evaluation import EvaluationConfig, config_hash, run_evaluation
from trading_desk.market_data import Bar
from trading_desk.promotion import PromotionState

BASE = datetime(2026, 9, 3, 0, 0, tzinfo=timezone.utc)


def _config(**overrides) -> EvaluationConfig:
    fields = dict(
        instrument="gold",
        venue="mt5",
        symbol="XAUUSD",
        strategy_version="xau-ema-crossover@1",
        horizon="1h",
        equity=10_000.0,
        base_risk_pct=1.0,
        spread=0.30,
        slippage=0.10,
        commission_per_unit=0.02,
        max_holding_bars=10,
        train_size=60,
        test_size=30,
        step=30,
    )
    fields.update(overrides)
    return EvaluationConfig(**fields)


def _oscillating_bars(n: int) -> list[Bar]:
    """A series with repeated trends in both directions, so the EMA
    crossover actually fires multiple times across folds."""
    closes: list[float] = []
    price = 2500.0
    direction = 1
    for i in range(n):
        if i % 20 == 0:
            direction *= -1
        price += direction * 6.0
        closes.append(price)
    return [
        Bar(time=BASE + timedelta(hours=i), open=c - 0.5, high=c + 3.0, low=c - 3.0, close=c, volume=100)
        for i, c in enumerate(closes)
    ]


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------


def test_config_hash_is_stable_for_the_same_config() -> None:
    assert config_hash(_config()) == config_hash(_config())


def test_config_hash_changes_when_any_assumption_changes() -> None:
    base = config_hash(_config())
    assert config_hash(_config(spread=0.9)) != base
    assert config_hash(_config(base_risk_pct=2.0)) != base
    assert config_hash(_config(max_holding_bars=5)) != base


def test_evaluation_is_deterministic() -> None:
    bars = _oscillating_bars(200)
    first = run_evaluation(bars, _config())
    second = run_evaluation(bars, _config())
    assert first == second


def test_report_records_the_config_hash_it_was_produced_under() -> None:
    report = run_evaluation(_oscillating_bars(200), _config())
    assert report.config_hash == config_hash(_config())


# ---------------------------------------------------------------------------
# Walk-forward structure and leakage safety
# ---------------------------------------------------------------------------


def test_fold_count_matches_the_walk_forward_partitioning() -> None:
    from trading_desk.walk_forward import walk_forward_windows

    bars = _oscillating_bars(200)
    config = _config()
    expected = len(
        walk_forward_windows(bars, train_size=config.train_size, test_size=config.test_size, step=config.step)
    )
    assert run_evaluation(bars, config).fold_count == expected


def test_every_outcome_closes_inside_its_own_fold_test_window() -> None:
    """No fold may produce a trade that resolves using data from outside
    its evaluation window — that would be lookahead."""
    report = run_evaluation(_oscillating_bars(200), _config())
    for fold in report.folds:
        for outcome in fold.outcomes:
            assert fold.test_start <= outcome.opened_at <= fold.test_end
            assert fold.test_start <= outcome.closed_at <= fold.test_end


def test_future_bars_beyond_the_evaluated_range_cannot_change_results() -> None:
    """Appending later data must not alter already-evaluated folds. If it
    did, something in the pipeline is reading ahead."""
    bars = _oscillating_bars(200)
    report = run_evaluation(bars, _config())

    extended = bars + _oscillating_bars(260)[200:]
    extended_report = run_evaluation(extended, _config())

    for original, extended_fold in zip(report.folds, extended_report.folds):
        assert original.metrics["total_return_pct"] == pytest.approx(extended_fold.metrics["total_return_pct"])


# ---------------------------------------------------------------------------
# Aggregation, baseline and promotion wiring
# ---------------------------------------------------------------------------


def test_profitable_fold_ratio_is_a_fraction_of_folds() -> None:
    report = run_evaluation(_oscillating_bars(200), _config())
    assert report.profitable_fold_ratio is None or 0.0 <= report.profitable_fold_ratio <= 1.0


def test_aggregate_metrics_cover_every_fold_outcome() -> None:
    report = run_evaluation(_oscillating_bars(200), _config())
    total_trades = sum(len(fold.outcomes) for fold in report.folds)
    assert report.metrics["trade_count"] == total_trades


def test_baseline_is_computed_and_named() -> None:
    report = run_evaluation(_oscillating_bars(200), _config())
    assert report.baseline_comparison["baseline_version"] == "buy-and-hold@1"


def test_a_small_synthetic_sample_is_not_promoted() -> None:
    """A 200-bar synthetic run cannot meet the >=100 trade / >=90 day
    evidence bar. The report must say so rather than quietly passing."""
    report = run_evaluation(_oscillating_bars(200), _config())
    assert report.promotion.all_passed is False
    assert report.promotion.state is PromotionState.RESEARCH


def test_promotion_never_exceeds_paper_qualified_from_an_evaluation_run() -> None:
    report = run_evaluation(_oscillating_bars(200), _config())
    assert report.promotion.state in (PromotionState.RESEARCH, PromotionState.PAPER_QUALIFIED)


# ---------------------------------------------------------------------------
# Degenerate inputs
# ---------------------------------------------------------------------------


def test_insufficient_bars_produce_no_folds_and_an_unpromoted_report() -> None:
    report = run_evaluation(_oscillating_bars(20), _config())
    assert report.fold_count == 0
    assert report.folds == []
    assert report.promotion.all_passed is False


def test_no_bars_at_all_is_handled(tmp_path) -> None:
    report = run_evaluation([], _config())
    assert report.fold_count == 0
    assert report.metrics["trade_count"] == 0


# ---------------------------------------------------------------------------
# Artifact rendering
# ---------------------------------------------------------------------------


def test_markdown_artifact_includes_hash_folds_and_promotion_table() -> None:
    from trading_desk.evaluation import render_evaluation_markdown

    report = run_evaluation(_oscillating_bars(200), _config())
    text = render_evaluation_markdown(report)
    assert report.config_hash[:12] in text
    assert "Walk-forward folds" in text
    assert "Promotion gate report" in text


def test_markdown_is_ascii_safe_for_windows_consoles() -> None:
    """This project is Windows-first (MT5 is Windows-bound) and operators
    will read these in PowerShell, where the default cp1252 codec raises
    on characters like the arrow glyph."""
    from trading_desk.evaluation import render_evaluation_markdown

    text = render_evaluation_markdown(run_evaluation(_oscillating_bars(200), _config()))
    text.encode("cp1252")  # raises UnicodeEncodeError if a stray glyph creeps in


def test_saved_artifacts_are_written_and_reloadable(tmp_path) -> None:
    import json

    from trading_desk.evaluation import save_evaluation_artifacts

    report = run_evaluation(_oscillating_bars(200), _config())
    paths = save_evaluation_artifacts(report, tmp_path)

    assert paths["json"].is_file() and paths["markdown"].is_file()
    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert payload["config_hash"] == report.config_hash
    assert payload["promotion"]["state"] == report.promotion.state.value
    assert len(payload["folds"]) == report.fold_count
    # Every gate's evidence survives into the artifact, not just the verdict.
    assert all("source_metric" in gate and "reason" in gate for gate in payload["promotion"]["gates"])


def test_artifacts_for_different_configs_do_not_overwrite_each_other(tmp_path) -> None:
    from trading_desk.evaluation import save_evaluation_artifacts

    bars = _oscillating_bars(200)
    first = save_evaluation_artifacts(run_evaluation(bars, _config()), tmp_path)
    second = save_evaluation_artifacts(run_evaluation(bars, _config(spread=0.9)), tmp_path)

    assert first["json"] != second["json"]
    assert first["json"].is_file() and second["json"].is_file()
