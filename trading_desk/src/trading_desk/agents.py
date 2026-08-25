from __future__ import annotations

import json
import re
from typing import Any

from trading_desk.llm import OpenRouterClient

SYSTEM = (
    "You are a markets research desk covering gold, equity indices, and crypto. "
    "Use only the supplied numbers and headlines. Do not invent prices or indicators. "
    "If data is thin, say so and lower confidence. Reply with a single JSON object, no markdown."
)


def _parse_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return {"raw": text, "parse_error": True}
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {"raw": text, "parse_error": True}
    return data if isinstance(data, dict) else {"raw": data, "parse_error": True}


def ask(client: OpenRouterClient, role: str, schema: str, payload: dict[str, Any]) -> dict[str, Any]:
    user = (
        f"Role: {role}\n"
        f"Return JSON with keys: {schema}\n\n"
        f"Market pack:\n{json.dumps(payload, default=str)[:12000]}"
    )
    raw = client.complete(SYSTEM, user)
    parsed = _parse_json(raw)
    parsed["_role"] = role
    parsed["_model"] = client.model_used
    return parsed


def technical(client: OpenRouterClient, market: dict[str, Any]) -> dict[str, Any]:
    return ask(
        client,
        "technical_analyst",
        "bias (bullish|bearish|neutral), confidence (0-100), summary, "
        "key_levels (list), invalidation, key_points (list of strings)",
        {"focus": "price structure, RSI, MACD, MAs, ATR, 20-day range", "market": market},
    )


def news_macro(client: OpenRouterClient, market: dict[str, Any]) -> dict[str, Any]:
    return ask(
        client,
        "news_macro_analyst",
        "bias (bullish|bearish|neutral), confidence (0-100), summary, "
        "drivers (list), risks (list), key_points (list of strings)",
        {
            "focus": (
                "For gold: DXY, real rates, geopolitics. "
                "For indices: risk appetite, VIX, rates. "
                "For crypto: liquidity, BTC lead, ETF/news flow. "
                "Use headlines only as claims, not facts."
            ),
            "market": market,
        },
    )


def researcher(client: OpenRouterClient, stance: str, pack: dict[str, Any]) -> dict[str, Any]:
    return ask(
        client,
        f"{stance}_researcher",
        "stance, confidence (0-100), thesis, strongest_points (list), weakest_points (list)",
        {"required_stance": stance, "evidence": pack},
    )


def trader(client: OpenRouterClient, pack: dict[str, Any]) -> dict[str, Any]:
    return ask(
        client,
        "trader",
        "action (BUY|SELL|HOLD), confidence (0-100), horizon (intraday|swing|position), "
        "entry, stop, targets (list), size_pct (0-5), rationale",
        {
            "mandate": (
                "Prefer HOLD when evidence conflicts or data is thin. "
                "size_pct is percent of paper equity, never above 5. "
                "Stops must be described relative to ATR or a level from the pack."
            ),
            "evidence": pack,
        },
    )


def risk(client: OpenRouterClient, pack: dict[str, Any]) -> dict[str, Any]:
    return ask(
        client,
        "risk_manager",
        "verdict (APPROVE|REDUCE|REJECT), max_size_pct (0-5), risks (list), rationale",
        {
            "mandate": "Reject if stop is missing, size > 5, or thesis is only narrative with no levels.",
            "proposal": pack,
        },
    )


def trader_and_risk(client: OpenRouterClient, pack: dict[str, Any]) -> dict[str, Any]:
    return ask(
        client,
        "trader_risk",
        "action (BUY|SELL|HOLD), confidence (0-100), horizon (intraday|swing|position), "
        "entry, stop, targets (list), size_pct (0-5), verdict (APPROVE|REDUCE|REJECT), "
        "max_size_pct (0-5), rationale, risks (list)",
        {
            "mandate": "Combine trader and risk in one object. Default to HOLD + REDUCE when unsure.",
            "evidence": pack,
        },
    )


def heuristic_decision(market: dict[str, Any]) -> dict[str, Any]:
    """Rule stub for --dry-run so the desk works without an API key."""
    daily = market.get("daily") or {}
    rsi_val = daily.get("rsi_14")
    hist = daily.get("macd_hist")
    action = "HOLD"
    rationale = "Dry-run heuristic: mixed or missing oscillator confirmation."
    if isinstance(rsi_val, (int, float)) and isinstance(hist, (int, float)):
        if rsi_val < 35 and hist > 0:
            action = "BUY"
            rationale = "Dry-run heuristic: RSI below 35 with positive MACD histogram."
        elif rsi_val > 65 and hist < 0:
            action = "SELL"
            rationale = "Dry-run heuristic: RSI above 65 with negative MACD histogram."
    return {
        "_role": "dry_run_heuristic",
        "_model": None,
        "action": action,
        "confidence": 35,
        "horizon": "swing",
        "entry": daily.get("last_close"),
        "stop": daily.get("atr_14"),
        "targets": [],
        "size_pct": 0,
        "verdict": "REJECT",
        "max_size_pct": 0,
        "rationale": rationale + " Not an order. Risk rejects all dry-run signals.",
        "risks": ["No LLM review", "Research feed only, not broker quotes", "Heuristic is not a strategy"],
    }
