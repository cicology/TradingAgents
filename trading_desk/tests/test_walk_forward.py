"""TA-303: chronological partitions and walk-forward folds.

The acceptance criterion is literal: every evaluation row must postdate
every training row. These tests do not just check that the happy path
produces the right shapes — they also feed the leakage detector data that
*does* leak and assert it catches it, because a detector that never fires
is indistinguishable from no detector at all.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from trading_desk.market_data import Bar
from trading_desk.walk_forward import (
    LeakageError,
    assert_no_leakage,
    chronological_split,
    walk_forward_windows,
)

BASE = datetime(2026, 9, 3, 0, 0, tzinfo=timezone.utc)


def _bars(n: int) -> list[Bar]:
    return [
        Bar(time=BASE + timedelta(hours=i), open=100.0 + i, high=101.0 + i, low=99.0 + i, close=100.5 + i, volume=10)
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# chronological_split
# ---------------------------------------------------------------------------


def test_split_sizes_follow_the_requested_fractions() -> None:
    train, validation, test = chronological_split(_bars(100), train_frac=0.6, validation_frac=0.2)
    assert (len(train), len(validation), len(test)) == (60, 20, 20)


def test_split_partitions_are_contiguous_and_lose_no_bars() -> None:
    bars = _bars(100)
    train, validation, test = chronological_split(bars, train_frac=0.6, validation_frac=0.2)
    assert train + validation + test == bars


def test_every_validation_row_postdates_every_training_row() -> None:
    train, validation, _ = chronological_split(_bars(100), train_frac=0.6, validation_frac=0.2)
    assert min(b.time for b in validation) > max(b.time for b in train)


def test_every_test_row_postdates_every_validation_row() -> None:
    _, validation, test = chronological_split(_bars(100), train_frac=0.6, validation_frac=0.2)
    assert min(b.time for b in test) > max(b.time for b in validation)


def test_unsorted_bars_are_rejected_rather_than_silently_mis_split() -> None:
    bars = _bars(10)
    shuffled = [bars[5]] + bars[:5] + bars[6:]
    with pytest.raises(LeakageError, match="chronological order"):
        chronological_split(shuffled, train_frac=0.6, validation_frac=0.2)


def test_fractions_that_leave_no_test_partition_are_rejected() -> None:
    with pytest.raises(ValueError, match="non-empty test partition"):
        chronological_split(_bars(100), train_frac=0.9, validation_frac=0.1)


def test_too_few_bars_to_populate_every_partition_is_rejected() -> None:
    with pytest.raises(ValueError, match="too few bars"):
        chronological_split(_bars(2), train_frac=0.6, validation_frac=0.2)


# ---------------------------------------------------------------------------
# walk_forward_windows
# ---------------------------------------------------------------------------


def test_walk_forward_produces_the_expected_number_of_folds() -> None:
    folds = walk_forward_windows(_bars(100), train_size=50, test_size=10, step=10)
    # starts at 0,10,20,30,40 -> train[0:50]+test[50:60] ... train[40:90]+test[90:100]
    assert len(folds) == 5


def test_every_fold_test_set_postdates_its_own_training_set() -> None:
    for fold in walk_forward_windows(_bars(100), train_size=50, test_size=10, step=10):
        assert min(b.time for b in fold.test) > max(b.time for b in fold.train)


def test_fold_sizes_are_exact() -> None:
    for fold in walk_forward_windows(_bars(100), train_size=50, test_size=10, step=10):
        assert len(fold.train) == 50
        assert len(fold.test) == 10


def test_folds_advance_forward_in_time() -> None:
    folds = walk_forward_windows(_bars(100), train_size=50, test_size=10, step=10)
    starts = [f.train[0].time for f in folds]
    assert starts == sorted(starts)
    assert len(set(starts)) == len(starts)


def test_partial_trailing_window_is_dropped_not_padded() -> None:
    """A final window without a full test set is dropped. Padding or
    short-changing it would quietly evaluate on less data than claimed."""
    folds = walk_forward_windows(_bars(95), train_size=50, test_size=10, step=10)
    assert all(len(f.test) == 10 for f in folds)
    assert len(folds) == 4  # the 5th would need bars up to index 100


def test_insufficient_data_yields_no_folds_rather_than_a_degenerate_one() -> None:
    assert walk_forward_windows(_bars(30), train_size=50, test_size=10, step=10) == []


def test_walk_forward_rejects_unsorted_bars() -> None:
    bars = _bars(100)
    shuffled = [bars[50]] + bars[:50] + bars[51:]
    with pytest.raises(LeakageError, match="chronological order"):
        walk_forward_windows(shuffled, train_size=50, test_size=10, step=10)


# ---------------------------------------------------------------------------
# assert_no_leakage — the detector must actually fire
# ---------------------------------------------------------------------------


def test_leakage_detector_accepts_a_clean_split() -> None:
    bars = _bars(20)
    assert_no_leakage(bars[:10], bars[10:])  # does not raise


def test_leakage_detector_catches_an_overlapping_bar() -> None:
    bars = _bars(20)
    with pytest.raises(LeakageError, match="postdate"):
        assert_no_leakage(bars[:10], bars[9:])  # bar 9 appears in both


def test_leakage_detector_catches_a_test_row_that_predates_training() -> None:
    bars = _bars(20)
    with pytest.raises(LeakageError, match="postdate"):
        assert_no_leakage(bars[10:], bars[:10])  # test entirely before train


def test_leakage_detector_catches_an_identical_timestamp() -> None:
    bars = _bars(20)
    with pytest.raises(LeakageError, match="postdate"):
        assert_no_leakage(bars[:10], [bars[9]])


def test_leakage_detector_treats_empty_sets_as_nothing_to_check() -> None:
    bars = _bars(20)
    assert_no_leakage(bars[:10], [])
    assert_no_leakage([], bars[10:])
