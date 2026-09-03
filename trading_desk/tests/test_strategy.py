"""TA-202: the deterministic EMA-crossover strategy is the XAU/USD
vertical slice's first versioned strategy — no LLM involved, so the desk
stays operable with no provider configured and results are bit-for-bit
reproducible."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from trading_desk.market_data import Bar
from trading_desk.strategy import MIN_BARS, ema_crossover_proposal

STRATEGY_VERSION = "xau-ema-crossover@1"


def _bars(closes: list[float]) -> list[Bar]:
    base = datetime(2026, 9, 3, 0, 0, tzinfo=timezone.utc)
    return [
        Bar(
            time=base + timedelta(hours=i),
            open=c - 0.5,
            high=c + 1.0,
            low=c - 1.0,
            close=c,
            volume=100,
        )
        for i, c in enumerate(closes)
    ]


def test_insufficient_history_holds_and_rejects() -> None:
    proposal = ema_crossover_proposal(_bars([2500.0] * 5), strategy_version=STRATEGY_VERSION)
    assert proposal["action"] == "HOLD"
    assert proposal["verdict"] == "REJECT"


def test_sustained_uptrend_produces_a_buy_crossover() -> None:
    # 25 bars declining, then a 5-bar reversal sharp enough that the 9-EMA
    # crosses above the 21-EMA exactly on the last bar (verified offline —
    # this is not a "maybe" fixture).
    closes = [2550.0 - i * 3 for i in range(25)] + [2550.0 - 24 * 3 + j * 15 for j in range(1, 6)]
    proposal = ema_crossover_proposal(_bars(closes), strategy_version=STRATEGY_VERSION)
    assert proposal["action"] == "BUY"
    assert proposal["verdict"] == "APPROVE"
    assert proposal["stop"] < proposal["entry"]
    assert proposal["targets"][0] > proposal["entry"]


def test_sustained_downtrend_produces_a_sell_crossover() -> None:
    closes = [2450.0 + i * 3 for i in range(25)] + [2450.0 + 24 * 3 - j * 15 for j in range(1, 6)]
    proposal = ema_crossover_proposal(_bars(closes), strategy_version=STRATEGY_VERSION)
    assert proposal["action"] == "SELL"
    assert proposal["verdict"] == "APPROVE"
    assert proposal["stop"] > proposal["entry"]
    assert proposal["targets"][0] < proposal["entry"]


def test_flat_series_holds() -> None:
    proposal = ema_crossover_proposal(_bars([2500.0] * (MIN_BARS + 5)), strategy_version=STRATEGY_VERSION)
    assert proposal["action"] == "HOLD"
    assert proposal["verdict"] == "REJECT"


def test_proposal_is_deterministic_across_repeated_calls() -> None:
    closes = [2550.0 - i * 3 for i in range(25)] + [2550.0 - 24 * 3 + j * 15 for j in range(1, 6)]
    bars = _bars(closes)
    first = ema_crossover_proposal(bars, strategy_version=STRATEGY_VERSION)
    second = ema_crossover_proposal(bars, strategy_version=STRATEGY_VERSION)
    assert first == second
    assert first["action"] == "BUY"


def test_proposal_carries_strategy_version_for_traceability() -> None:
    proposal = ema_crossover_proposal(_bars([2500.0] * (MIN_BARS + 5)), strategy_version=STRATEGY_VERSION)
    assert proposal["_strategy_version"] == STRATEGY_VERSION
