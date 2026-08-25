from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from trading_desk.config import REPORTS_DIR


def write_run(result: dict[str, Any]) -> tuple[Path, Path]:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    stamp = datetime.now(timezone.utc).strftime("%H%M%S")
    name = result["instrument"]["name"]
    folder = REPORTS_DIR / day
    folder.mkdir(parents=True, exist_ok=True)
    json_path = folder / f"{name}-{stamp}.json"
    md_path = folder / f"{name}-{stamp}.md"
    json_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    md_path.write_text(_markdown(result), encoding="utf-8")
    _append_ledger(result, json_path)
    return json_path, md_path


def _append_ledger(result: dict[str, Any], json_path: Path) -> None:
    decision = result.get("decision") or {}
    line = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "instrument": result["instrument"]["name"],
        "symbol": result["instrument"]["symbol"],
        "mode": result.get("mode"),
        "action": decision.get("action"),
        "verdict": decision.get("verdict"),
        "confidence": decision.get("confidence"),
        "size_pct": decision.get("size_pct"),
        "mt5_status": (result.get("mt5") or {}).get("status"),
        "report": str(json_path),
    }
    ledger = REPORTS_DIR / "paper_ledger.jsonl"
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, default=str) + "\n")


def _markdown(result: dict[str, Any]) -> str:
    inst = result["instrument"]
    daily = (result.get("market") or {}).get("daily") or {}
    decision = result.get("decision") or {}
    headlines = (result.get("market") or {}).get("headlines") or []
    lines = [
        f"# {inst['name']} ({inst['symbol']})",
        "",
        f"- Class: {inst['asset_class']}",
        f"- Mode: {result.get('mode')}",
        f"- Feed: {(result.get('market') or {}).get('source')}",
        f"- As of: {daily.get('as_of')}",
        f"- Last: {daily.get('last_close')} ({daily.get('day_change_pct')}%)",
        f"- RSI(14): {daily.get('rsi_14')} | MACD hist: {daily.get('macd_hist')} | ATR: {daily.get('atr_14')}",
        f"- SMA20/50/200: {daily.get('sma_20')} / {daily.get('sma_50')} / {daily.get('sma_200')}",
        "",
        "## Decision",
        "",
        f"- Action: **{decision.get('action')}**",
        f"- Risk verdict: **{decision.get('verdict')}**",
        f"- Confidence: {decision.get('confidence')}",
        f"- Horizon: {decision.get('horizon')}",
        f"- Size (% paper equity): {decision.get('size_pct')} (cap {decision.get('max_size_pct')})",
        f"- Entry: {decision.get('entry')}",
        f"- Stop: {decision.get('stop')}",
        f"- Targets: {decision.get('targets')}",
        "",
    ]
    kelly = decision.get("kelly")
    if kelly:
        lines.extend(
            [
                "## Kelly sizing",
                "",
                f"- Win rate used (shrunk): {kelly.get('win_rate_used')}",
                f"- Reward/risk: {kelly.get('reward_risk')}",
                f"- Full Kelly: {kelly.get('full')}%",
                f"- Fractional ({kelly.get('fraction_of_full')}): {kelly.get('fractional')}%",
                f"- After {kelly.get('cap_pct')}% cap: **{kelly.get('capped')}%**",
                f"- {kelly.get('note')}",
                "",
            ]
        )
    lines.extend(
        [
            str(decision.get("rationale") or ""),
            "",
            "## Risks",
            "",
        ]
    )
    risks = decision.get("risks") or []
    if risks:
        lines.extend(f"- {item}" for item in risks)
    else:
        lines.append("- (none listed)")
    lines.extend(["", "## Headlines", ""])
    if headlines:
        for item in headlines:
            pub = f" ({item.get('publisher')})" if item.get("publisher") else ""
            lines.append(f"- {item.get('title')}{pub}")
    else:
        lines.append("- None returned by Yahoo.")
    brue = result.get("brue")
    if brue:
        lines.extend(
            [
                "",
                "## Brue",
                "",
                f"- Script: {brue.get('script')}",
                f"- Last signal: **{brue.get('last_signal')}**",
                f"- Source: `{brue.get('source')}`",
                f"- {brue.get('rationale') or ''}",
                "",
            ]
        )
    mt5_exec = result.get("mt5")
    if mt5_exec:
        lines.extend(
            [
                "",
                "## MetaTrader 5",
                "",
                f"- Status: **{mt5_exec.get('status')}**",
                f"- Symbol: {mt5_exec.get('mt5_symbol')}",
                f"- Volume: {mt5_exec.get('volume')}",
                f"- Side: {mt5_exec.get('side')}",
                f"- Price: {mt5_exec.get('price')}",
                f"- SL/TP: {mt5_exec.get('sl')} / {mt5_exec.get('tp')}",
                f"- Reason: {mt5_exec.get('reason') or 'n/a'}",
                "",
            ]
        )
    lines.extend(
        [
            "",
            "## Disclaimer",
            "",
            "Research output only. Not financial advice. Not a live order.",
            "",
        ]
    )
    return "\n".join(lines) + "\n"
