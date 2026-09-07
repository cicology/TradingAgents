"""TA-303: chronological partitions and walk-forward folds.

Financial backtests leak by default: shuffle the rows, fit on data that
includes the future, or evaluate on a window the parameters were chosen
from, and the result looks excellent and means nothing. Everything here
is built so that the only way to get a partition is one where every
evaluation row postdates every training row.

`LeakageError` is raised — never warned, never silently corrected —
because a leaked split does not produce a slightly-worse number, it
produces a number that cannot be interpreted at all.
"""

from __future__ import annotations

from dataclasses import dataclass

from trading_desk.market_data import Bar


class LeakageError(RuntimeError):
    """Raised when data ordering would let future information reach a
    training or evaluation window."""


@dataclass(frozen=True)
class WalkForwardFold:
    index: int
    train: list[Bar]
    test: list[Bar]


def _require_chronological(bars: list[Bar]) -> None:
    """Bars must already be oldest-first. This module refuses to sort them
    itself: silently reordering a caller's data would hide the fact that
    the caller's pipeline produced it out of order, which is exactly the
    kind of bug that causes leakage elsewhere."""
    for earlier, later in zip(bars, bars[1:]):
        if later.time <= earlier.time:
            raise LeakageError(
                "bars must be in strict chronological order (oldest first); "
                f"{later.time.isoformat()} does not follow {earlier.time.isoformat()}"
            )


def assert_no_leakage(train: list[Bar], test: list[Bar]) -> None:
    """Every test bar must strictly postdate every training bar.

    Empty sets are treated as nothing to check rather than as a violation —
    an empty fold is a sizing question, not a leakage question.
    """
    if not train or not test:
        return
    latest_train = max(b.time for b in train)
    earliest_test = min(b.time for b in test)
    if earliest_test <= latest_train:
        raise LeakageError(
            "evaluation rows must postdate every training row; "
            f"earliest test bar {earliest_test.isoformat()} does not postdate "
            f"latest train bar {latest_train.isoformat()}"
        )


def chronological_split(
    bars: list[Bar], *, train_frac: float, validation_frac: float
) -> tuple[list[Bar], list[Bar], list[Bar]]:
    """Split bars into contiguous train/validation/test partitions in time
    order. No shuffling, no random state — the test partition is always
    the most recent data."""
    if train_frac <= 0 or validation_frac <= 0:
        raise ValueError("train_frac and validation_frac must both be positive fractions")
    if train_frac + validation_frac >= 1.0:
        raise ValueError(
            "train_frac + validation_frac must leave a non-empty test partition "
            f"(got {train_frac} + {validation_frac})"
        )
    _require_chronological(bars)

    train_end = int(len(bars) * train_frac)
    validation_end = train_end + int(len(bars) * validation_frac)
    train = bars[:train_end]
    validation = bars[train_end:validation_end]
    test = bars[validation_end:]

    if not train or not validation or not test:
        raise ValueError(
            f"too few bars ({len(bars)}) to populate every partition at "
            f"train_frac={train_frac}, validation_frac={validation_frac}"
        )

    assert_no_leakage(train, validation)
    assert_no_leakage(train + validation, test)
    return train, validation, test


def walk_forward_windows(
    bars: list[Bar], *, train_size: int, test_size: int, step: int
) -> list[WalkForwardFold]:
    """Rolling train/test folds advancing forward in time.

    A trailing window without a full test set is dropped rather than
    padded or shortened: evaluating on fewer bars than claimed would
    silently change what the reported metrics mean.
    """
    if train_size <= 0 or test_size <= 0 or step <= 0:
        raise ValueError("train_size, test_size and step must all be positive")
    _require_chronological(bars)

    folds: list[WalkForwardFold] = []
    start = 0
    index = 0
    while start + train_size + test_size <= len(bars):
        train = bars[start : start + train_size]
        test = bars[start + train_size : start + train_size + test_size]
        assert_no_leakage(train, test)
        folds.append(WalkForwardFold(index=index, train=train, test=test))
        start += step
        index += 1
    return folds
