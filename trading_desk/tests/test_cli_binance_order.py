"""TA-007: `desk binance order` must size quantity from risk inputs, not
accept a raw manually-typed quantity that bypasses shared risk/exposure
controls."""

from __future__ import annotations

import json

import pytest

from trading_desk import binance_bridge, cli


def test_binance_order_sizes_quantity_from_risk(
    monkeypatch: pytest.MonkeyPatch, isolated_risk_state, capsys: pytest.CaptureFixture[str]
) -> None:
    captured_extra: list[str] = []

    def fake_invoke(command: str, extra: list[str] | None = None, timeout: float = 45.0):
        captured_extra.extend(extra or [])
        return {"status": "paper-logged", "symbol": (extra or [None])[0]}

    monkeypatch.setattr(binance_bridge, "invoke", fake_invoke)

    code = cli.main(
        ["binance", "order", "btc", "BUY", "--equity", "10000", "--entry", "50000", "--stop", "49000"]
    )

    assert code == 0
    # quantity_from_risk(10000, 0.5%, 50000, 49000) == 0.05
    assert captured_extra[2] == "0.05"
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["status"] == "paper-logged"


def test_binance_order_rejects_invalid_stop_direction(capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(
        ["binance", "order", "btc", "BUY", "--equity", "10000", "--entry", "50000", "--stop", "51000"]
    )

    assert code != 0
    captured = capsys.readouterr()
    assert "stop must be below entry" in captured.err.lower()
