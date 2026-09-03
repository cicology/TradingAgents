"""TA-007: Binance sizing must route through the same deterministic
risk/exposure pipeline as MT5 — no arbitrary manual quantity that bypasses
the shared position-size cap, step/minimum-quantity/minimum-notional
filters, or stop-direction validation."""

from __future__ import annotations

import pytest

from trading_desk.binance_bridge import quantity_from_risk


def test_linear_contract_quantity_uses_stop_loss_budget() -> None:
    quantity = quantity_from_risk(equity=10_000, size_pct=0.5, entry=50_000, stop=49_000)
    assert quantity == pytest.approx(0.05)


def test_invalid_stop_direction_is_rejected_for_buy() -> None:
    with pytest.raises(ValueError, match="stop must be below entry"):
        quantity_from_risk(equity=10_000, size_pct=0.5, entry=50_000, stop=51_000, side="BUY")


def test_invalid_stop_direction_is_rejected_for_sell() -> None:
    with pytest.raises(ValueError, match="stop must be above entry"):
        quantity_from_risk(equity=10_000, size_pct=0.5, entry=50_000, stop=49_000, side="SELL")


def test_size_above_shared_cap_is_clipped() -> None:
    """size_pct above the shared MAX_POSITION_PCT cap must be clipped, not
    used as-is — this is the same cap MT5 sizing is bound by."""
    quantity = quantity_from_risk(equity=10_000, size_pct=20, entry=50_000, stop=49_000)
    assert quantity == pytest.approx(0.5)


def test_non_positive_inputs_are_rejected() -> None:
    with pytest.raises(ValueError):
        quantity_from_risk(equity=0, size_pct=0.5, entry=50_000, stop=49_000)
    with pytest.raises(ValueError):
        quantity_from_risk(equity=10_000, size_pct=0.5, entry=0, stop=49_000)


def test_quantity_below_step_is_rejected_not_rounded_up() -> None:
    """A tiny risk budget that computes to less than one exchange lot step
    must be rejected, never bumped up to the minimum — that would size
    above what was approved (mirrors the MT5 minimum-volume fix)."""
    with pytest.raises(ValueError, match="below the exchange minimum"):
        quantity_from_risk(
            equity=10_000, size_pct=0.01, entry=50_000, stop=40_000, step=0.001, min_qty=0.001
        )


def test_quantity_rounds_down_to_step() -> None:
    quantity = quantity_from_risk(
        equity=10_000, size_pct=0.5, entry=50_000, stop=49_000, step=0.01
    )
    assert quantity == pytest.approx(0.05)


def test_quantity_below_minimum_notional_is_rejected() -> None:
    with pytest.raises(ValueError, match="minimum notional"):
        quantity_from_risk(
            equity=10_000, size_pct=0.01, entry=50_000, stop=45_000, min_notional=50.0
        )


def test_fee_rate_reduces_effective_size_but_never_increases_it() -> None:
    baseline = quantity_from_risk(equity=10_000, size_pct=0.5, entry=50_000, stop=49_000)
    with_fees = quantity_from_risk(equity=10_000, size_pct=0.5, entry=50_000, stop=49_000, fee_rate=0.001)
    assert 0 < with_fees < baseline
