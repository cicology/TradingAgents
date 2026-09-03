"""TA-006: the CLI exposes an explicit close so record_close() has an
operator-facing caller and lifecycle state cannot silently go stale."""

from __future__ import annotations

import pytest

from trading_desk import cli, risk


def test_risk_close_records_pnl_and_clears_position(
    isolated_risk_state, capsys: pytest.CaptureFixture[str]
) -> None:
    risk.record_open("mt5", "XAUUSD", "BUY", size_pct=0.5)

    code = cli.main(["risk", "close", "mt5", "XAUUSD", "--realized-pnl-pct", "-0.4"])

    assert code == 0
    assert risk.open_positions() == {}
    breached, pnl = risk.daily_loss_breached()
    assert not breached
    assert pnl == pytest.approx(-0.4)


def test_risk_close_unknown_position_fails_closed(
    isolated_risk_state, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli.main(["risk", "close", "mt5", "NOPOSITION", "--realized-pnl-pct", "0"])

    assert code != 0
