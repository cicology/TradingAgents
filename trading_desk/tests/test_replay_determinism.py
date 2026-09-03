"""TA-202 acceptance criterion: 'replayed decision has identical evidence
hash'. Runs the full bars -> evidence -> strategy -> validate -> size
pipeline twice on the same bars and proves both the evidence hash and the
resulting TradeDecision are bit-for-bit identical — the deterministic
strategy path has no hidden nondeterminism (randomness, wall-clock
dependence beyond the injected `now`, dict-ordering, etc.)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from trading_desk.domain import MarketSnapshot
from trading_desk.evidence import compute_evidence_hash
from trading_desk.market_data import Bar
from trading_desk.sizing import size_decision
from trading_desk.strategy import ema_crossover_proposal
from trading_desk.validation import validate_decision

STRATEGY_VERSION = "xau-ema-crossover@1"
NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)


def _bars() -> list[Bar]:
    base = datetime(2026, 9, 3, 0, 0, tzinfo=timezone.utc)
    closes = [2550.0 - i * 3 for i in range(25)] + [2550.0 - 24 * 3 + j * 15 for j in range(1, 6)]
    return [
        Bar(time=base + timedelta(hours=i), open=c - 0.5, high=c + 1.0, low=c - 1.0, close=c, volume=100)
        for i, c in enumerate(closes)
    ]


def _run_once(bars: list[Bar]):
    evidence_hash = compute_evidence_hash(bars, instrument="gold", horizon="1h")
    proposal = ema_crossover_proposal(bars, strategy_version=STRATEGY_VERSION)
    last_bar = bars[-1]
    market = MarketSnapshot(instrument="gold", as_of=last_bar.time, last_close=last_bar.close)
    decision = validate_decision(
        proposal, instrument="gold", strategy_version=STRATEGY_VERSION,
        market=market, horizon="1h", now=NOW,
    )
    sized = size_decision(decision, base_risk_pct=1.0)
    return evidence_hash, sized


def test_replaying_the_same_bars_produces_identical_evidence_hash_and_decision() -> None:
    bars = _bars()

    hash_1, decision_1 = _run_once(bars)
    hash_2, decision_2 = _run_once(bars)

    assert hash_1 == hash_2
    assert decision_1 == decision_2
    assert decision_1.action.value == "BUY"
    assert decision_1.size_pct > 0


def test_a_different_bar_changes_both_the_hash_and_the_decision() -> None:
    bars = _bars()
    mutated = list(bars)
    mutated[-1] = Bar(
        time=mutated[-1].time, open=mutated[-1].open, high=mutated[-1].high,
        low=mutated[-1].low, close=mutated[-1].close - 50.0, volume=mutated[-1].volume,
    )

    hash_original, decision_original = _run_once(bars)
    hash_mutated, decision_mutated = _run_once(mutated)

    assert hash_original != hash_mutated
    assert decision_original != decision_mutated
