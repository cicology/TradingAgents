from __future__ import annotations

from typing import Any

from trading_desk.agents import heuristic_decision, news_macro, researcher, risk, technical, trader, trader_and_risk
from trading_desk.config import KELLY_CAP, KELLY_FRACTION
from trading_desk.instruments import Instrument
from trading_desk.kelly import size_for_trade
from trading_desk.llm import OpenRouterClient
from trading_desk.market import load_market


def run_analysis(instrument: Instrument, mode: str = "quick", dry_run: bool = False) -> dict[str, Any]:
    if mode not in {"quick", "full"}:
        raise ValueError("mode must be 'quick' or 'full'")

    market = load_market(instrument)
    result: dict[str, Any] = {
        "instrument": market["instrument"],
        "mode": "dry-run" if dry_run else mode,
        "market": {
            "source": market.get("source"),
            "daily": market["daily"],
            "intraday": market.get("intraday"),
            "intraday_source": market.get("intraday_source"),
            "headlines": market["headlines"],
            "cross_asset": market["cross_asset"],
            "recent_closes": market["recent_closes"],
        },
        "agents": {},
    }

    if dry_run:
        decision = heuristic_decision(market)
        result["agents"]["trader_risk"] = decision
        result["decision"] = _normalize_decision(decision)
        return result

    client = OpenRouterClient()
    tech = technical(client, market)
    news = news_macro(client, market)
    result["agents"]["technical"] = tech
    result["agents"]["news_macro"] = news
    evidence: dict[str, Any] = {"market": market, "technical": tech, "news_macro": news}

    if mode == "full":
        bull = researcher(client, "bull", evidence)
        bear = researcher(client, "bear", evidence)
        result["agents"]["bull"] = bull
        result["agents"]["bear"] = bear
        evidence["bull"] = bull
        evidence["bear"] = bear
        trade = trader(client, evidence)
        result["agents"]["trader"] = trade
        judged = risk(client, {"trader": trade, "evidence": evidence})
        result["agents"]["risk"] = judged
        result["decision"] = _merge_full(trade, judged)
        result["model_used"] = client.model_used
        return result

    combined = trader_and_risk(client, evidence)
    result["agents"]["trader_risk"] = combined
    result["decision"] = _normalize_decision(combined)
    result["model_used"] = client.model_used
    return result


def _normalize_decision(block: dict[str, Any]) -> dict[str, Any]:
    action = str(block.get("action") or "HOLD").upper()
    if action not in {"BUY", "SELL", "HOLD"}:
        action = "HOLD"
    verdict = str(block.get("verdict") or "REDUCE").upper()
    if verdict not in {"APPROVE", "REDUCE", "REJECT"}:
        verdict = "REDUCE"
    size = 0.0
    max_size = 0.0
    kelly = None
    if verdict not in {"REJECT"} and action in {"BUY", "SELL"}:
        frac = KELLY_FRACTION if verdict == "APPROVE" else max(0.25, KELLY_FRACTION / 2.0)
        kelly = size_for_trade(block, fraction_of_full=frac, cap=KELLY_CAP)
        max_size = round(kelly.cap * 100.0, 4)
        size = round(kelly.capped * 100.0, 4)
        if not kelly.edge:
            size = 0.0
            max_size = 0.0
            verdict = "REJECT"
    payload = {
        "action": action,
        "confidence": block.get("confidence"),
        "horizon": block.get("horizon"),
        "entry": block.get("entry"),
        "stop": block.get("stop"),
        "targets": block.get("targets") or [],
        "size_pct": size,
        "verdict": verdict,
        "max_size_pct": max_size,
        "rationale": block.get("rationale") or block.get("summary"),
        "risks": block.get("risks") or [],
    }
    if kelly is not None:
        payload["kelly"] = {
            "win_rate_used": round(kelly.win_rate, 4),
            "reward_risk": round(kelly.reward_risk, 4),
            "full": round(kelly.full * 100, 4),
            "fractional": round(kelly.fractional * 100, 4),
            "capped": round(kelly.capped * 100, 4),
            "fraction_of_full": kelly.fraction_of_full,
            "cap_pct": round(kelly.cap * 100, 4),
            "note": "Half-Kelly by default. Model confidence is shrunk; it is not a true win rate.",
        }
    return payload


def _merge_full(trade: dict[str, Any], judged: dict[str, Any]) -> dict[str, Any]:
    merged = {**trade, **{k: judged.get(k, trade.get(k)) for k in ("verdict", "max_size_pct", "risks", "rationale")}}
    if judged.get("rationale") and trade.get("rationale"):
        merged["rationale"] = f"Trader: {trade.get('rationale')} | Risk: {judged.get('rationale')}"
    return _normalize_decision(merged)
