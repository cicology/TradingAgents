"""Call the Kos-M/binance Node SDK via the local bridge CLI."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
BRIDGE_DIR = REPO_ROOT / "integrations" / "binance-bridge"
BRIDGE_ENTRY = BRIDGE_DIR / "cli.mjs"


def _node() -> str:
    exe = shutil.which("node")
    if not exe:
        raise RuntimeError("Node.js is required for the Binance SDK bridge. Install Node 18+ and retry.")
    return exe


def invoke(command: str, extra: list[str] | None = None, timeout: float = 45.0) -> dict[str, Any]:
    if not BRIDGE_ENTRY.is_file():
        raise RuntimeError(f"Missing Binance bridge at {BRIDGE_ENTRY}")
    args = [_node(), str(BRIDGE_ENTRY), command, *(extra or [])]
    env = os.environ.copy()
    completed = subprocess.run(
        args,
        cwd=str(BRIDGE_DIR),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        check=False,
    )
    stdout = (completed.stdout or "").strip()
    if completed.returncode != 0:
        err = (completed.stderr or stdout or "bridge failed").strip()
        raise RuntimeError(err)
    if not stdout:
        return {"ok": True}
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Bridge did not return JSON: {stdout[:500]}") from exc


def ping() -> dict[str, Any]:
    return invoke("ping")


def klines(symbol: str, interval: str = "1d", limit: int = 30) -> dict[str, Any]:
    return invoke("klines", [symbol, interval, str(limit)])


def paper_order(symbol: str, side: str, quantity: float, live: bool = False) -> dict[str, Any]:
    extra = [symbol, side.upper(), str(quantity)]
    if live:
        extra.append("--live")
    return invoke("order", extra)
