"""TA-002: known and adversarial CLI/env live-order bypass attempts must
all fail closed without reaching a broker or bridge process."""

from __future__ import annotations

import pytest

from trading_desk import binance_bridge, cli, mt5_broker


def _boom(*_args, **_kwargs):
    raise AssertionError("no adapter side effect should run for a rejected live request")


@pytest.fixture(autouse=True)
def _no_real_adapters(monkeypatch: pytest.MonkeyPatch) -> None:
    """Belt-and-braces: fail the test loudly if any live path reaches the
    real MT5 terminal or the Node bridge subprocess."""
    monkeypatch.setattr(mt5_broker, "connect", _boom)
    monkeypatch.setattr(binance_bridge, "invoke", _boom)


def test_mt5_order_live_flag_fails_closed(capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(["mt5", "order", "gold", "BUY", "--live"])

    assert code != 0
    captured = capsys.readouterr()
    assert "paper-only" in captured.err.lower()


def test_analyze_mt5_live_flag_fails_closed(capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(["analyze", "gold", "--dry-run", "--mt5-live"])

    assert code != 0


def test_binance_order_live_flag_fails_closed(capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(["binance", "order", "btc", "BUY", "0.001", "--live"])

    assert code != 0
    captured = capsys.readouterr()
    assert "paper-only" in captured.err.lower()


def test_binance_order_live_flag_fails_closed_even_with_legacy_env_set(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DESK_ALLOW_LIVE_ORDERS", "1")

    code = cli.main(["binance", "order", "btc", "BUY", "0.001", "--live"])

    assert code != 0
