"""TA-301: net performance and risk metrics.

Every expected value in this file is hand-calculated from the fixture
series below and written out in the test, so a metric change has to be a
deliberate decision rather than "the number moved and the test still
passed". No single headline number (return, Sharpe, win rate) is treated
as sufficient evidence anywhere — that is why drawdown, tail risk, and
streak metrics are computed alongside them.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from trading_desk.domain import Outcome
from trading_desk.metrics import compute_metrics

BASE = datetime(2026, 9, 3, 0, 0, tzinfo=timezone.utc)

# Hand-worked fixture:
#   pnls            :  2.0  -1.0   3.0  -2.0   1.0
#   equity curve    :  2.0   1.0   4.0   2.0   3.0
#   running peak    :  2.0   2.0   4.0   4.0   4.0
#   drawdown        :  0.0   1.0   0.0   2.0   1.0   -> max 2.0
PNLS = [2.0, -1.0, 3.0, -2.0, 1.0]


def _outcomes(pnls: list[float]) -> list[Outcome]:
    return [
        Outcome(
            venue="mt5",
            symbol="XAUUSD",
            strategy_version="xau-ema-crossover@1",
            opened_at=BASE + timedelta(hours=i),
            closed_at=BASE + timedelta(hours=i + 1),
            realized_pnl_pct=pnl,
        )
        for i, pnl in enumerate(pnls)
    ]


def test_trade_counts_are_exact() -> None:
    m = compute_metrics(_outcomes(PNLS))
    assert m["trade_count"] == 5
    assert m["win_count"] == 3
    assert m["loss_count"] == 2


def test_win_rate_is_wins_over_trades() -> None:
    m = compute_metrics(_outcomes(PNLS))
    assert m["win_rate"] == pytest.approx(0.6)


def test_total_return_is_the_sum_of_trade_returns() -> None:
    m = compute_metrics(_outcomes(PNLS))
    assert m["total_return_pct"] == pytest.approx(3.0)


def test_gross_profit_loss_and_profit_factor() -> None:
    m = compute_metrics(_outcomes(PNLS))
    assert m["gross_profit_pct"] == pytest.approx(6.0)
    assert m["gross_loss_pct"] == pytest.approx(3.0)
    assert m["profit_factor"] == pytest.approx(2.0)


def test_expectancy_and_average_win_loss() -> None:
    m = compute_metrics(_outcomes(PNLS))
    assert m["expectancy_pct"] == pytest.approx(0.6)  # 3.0 / 5
    assert m["avg_win_pct"] == pytest.approx(2.0)  # 6.0 / 3
    assert m["avg_loss_pct"] == pytest.approx(-1.5)  # -3.0 / 2


def test_max_drawdown_is_peak_to_trough_on_the_equity_curve() -> None:
    m = compute_metrics(_outcomes(PNLS))
    assert m["max_drawdown_pct"] == pytest.approx(2.0)


def test_tail_risk_reports_worst_trade_and_worst_decile_mean() -> None:
    m = compute_metrics(_outcomes(PNLS))
    assert m["worst_trade_pct"] == pytest.approx(-2.0)
    # worst 20% of 5 trades = 1 trade = -2.0
    assert m["worst_decile_mean_pct"] == pytest.approx(-2.0)


def test_longest_losing_streak_counts_consecutive_losses() -> None:
    # No two losses are adjacent in PNLS, so the longest streak is 1.
    assert compute_metrics(_outcomes(PNLS))["longest_losing_streak"] == 1
    # Three consecutive losses in the middle.
    streaky = [1.0, -1.0, -1.0, -1.0, 2.0]
    assert compute_metrics(_outcomes(streaky))["longest_losing_streak"] == 3


def test_all_losses_has_no_profit_factor_rather_than_dividing_by_zero() -> None:
    m = compute_metrics(_outcomes([-1.0, -2.0]))
    assert m["gross_profit_pct"] == pytest.approx(0.0)
    assert m["profit_factor"] is None  # undefined, not inf and not 0


def test_all_wins_has_no_profit_factor_rather_than_dividing_by_zero() -> None:
    m = compute_metrics(_outcomes([1.0, 2.0]))
    assert m["gross_loss_pct"] == pytest.approx(0.0)
    assert m["profit_factor"] is None
    assert m["max_drawdown_pct"] == pytest.approx(0.0)


def test_empty_outcome_list_is_well_formed_not_a_crash() -> None:
    m = compute_metrics([])
    assert m["trade_count"] == 0
    assert m["win_rate"] is None
    assert m["profit_factor"] is None
    assert m["total_return_pct"] == pytest.approx(0.0)
    assert m["max_drawdown_pct"] == pytest.approx(0.0)


def test_single_trade_has_no_stdev_based_ratio_rather_than_a_fake_one() -> None:
    """A one-trade sample has no meaningful dispersion — report None
    rather than a divide-by-zero or a fabricated 'infinite Sharpe'."""
    m = compute_metrics(_outcomes([1.0]))
    assert m["return_stdev_pct"] is None
    assert m["return_over_stdev"] is None


def test_return_over_stdev_matches_hand_calculation() -> None:
    # pnls [1.0, -1.0, 1.0, -1.0]: mean 0.0, sample stdev = sqrt(4/3) ~ 1.1547
    m = compute_metrics(_outcomes([1.0, -1.0, 1.0, -1.0]))
    assert m["return_stdev_pct"] == pytest.approx(1.1547, abs=1e-4)
    assert m["return_over_stdev"] == pytest.approx(0.0)


def test_metrics_are_deterministic() -> None:
    outcomes = _outcomes(PNLS)
    assert compute_metrics(outcomes) == compute_metrics(outcomes)
