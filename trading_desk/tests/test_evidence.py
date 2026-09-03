"""TA-202: evidence hashing must be deterministic — the same bars,
instrument, and horizon always produce the same evidence_id, so a
replayed run is provably reproducing the same inputs, not silently
drifting."""

from __future__ import annotations

from datetime import datetime, timezone

from trading_desk.evidence import compute_evidence_hash
from trading_desk.market_data import Bar


def _bars(n: int = 3) -> list[Bar]:
    base = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)
    return [
        Bar(time=base, open=2500.0 + i, high=2505.0 + i, low=2495.0 + i, close=2502.0 + i, volume=100)
        for i in range(n)
    ]


def test_same_inputs_produce_the_same_hash() -> None:
    bars = _bars()
    first = compute_evidence_hash(bars, instrument="gold", horizon="1h")
    second = compute_evidence_hash(bars, instrument="gold", horizon="1h")
    assert first == second


def test_different_instrument_changes_the_hash() -> None:
    bars = _bars()
    gold = compute_evidence_hash(bars, instrument="gold", horizon="1h")
    silver = compute_evidence_hash(bars, instrument="silver", horizon="1h")
    assert gold != silver


def test_different_horizon_changes_the_hash() -> None:
    bars = _bars()
    swing = compute_evidence_hash(bars, instrument="gold", horizon="1h")
    intraday = compute_evidence_hash(bars, instrument="gold", horizon="15m")
    assert swing != intraday


def test_a_single_changed_bar_changes_the_hash() -> None:
    bars = _bars()
    mutated = list(bars)
    mutated[-1] = Bar(
        time=mutated[-1].time, open=mutated[-1].open, high=mutated[-1].high,
        low=mutated[-1].low, close=mutated[-1].close + 0.01, volume=mutated[-1].volume,
    )
    assert compute_evidence_hash(bars, instrument="gold", horizon="1h") != compute_evidence_hash(
        mutated, instrument="gold", horizon="1h"
    )


def test_hash_is_a_stable_hex_digest_format() -> None:
    digest = compute_evidence_hash(_bars(), instrument="gold", horizon="1h")
    assert len(digest) == 64
    int(digest, 16)  # raises if not valid hex
