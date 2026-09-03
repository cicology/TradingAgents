"""TA-104: deterministic stop-risk sizing.

Size comes from configuration (`RISK_PCT_PER_TRADE`) and the decision's
verdict — never from LLM confidence. This is the executable sizing path
for the Phase 1+ canonical pipeline: `validation.validate_decision()`
produces an unsized `TradeDecision`, this module sizes it, and only the
result is ever turned into an `OrderIntent`.

Architectural Rule 2: "LLM output must never directly determine
executable quantity, exposure, margin, stop placement, or account risk."
`kelly.py`'s confidence-shrunk win-rate calculation is not used here and
remains a research-only annotation (see its own docstring) — it has no
wiring into this function or its output. An LLM-declared cap
(`declared_max_size_pct`, e.g. a risk agent's `max_size_pct` field) may
only ever shrink the deterministic result further, as a veto; it can
never grow it beyond `base_risk_pct`.
"""

from __future__ import annotations

import dataclasses

from trading_desk.config import RISK_PCT_PER_TRADE
from trading_desk.domain import Action, TradeDecision, Verdict

_VERDICT_MULTIPLIER = {
    Verdict.APPROVE: 1.0,
    Verdict.REDUCE: 0.5,
    Verdict.REJECT: 0.0,
}


def size_decision(
    decision: TradeDecision,
    *,
    base_risk_pct: float | None = None,
    declared_max_size_pct: float | None = None,
) -> TradeDecision:
    """Return a new TradeDecision with size_pct computed deterministically.

    @param base_risk_pct: percent of equity to risk on an APPROVE verdict.
        Defaults to the RISK_PCT_PER_TRADE config value. Never comes from
        an LLM proposal.
    @param declared_max_size_pct: an optional additional ceiling (e.g. a
        risk agent's declared cap). Malformed/negative input is ignored,
        not trusted as either a veto or an exemption; a valid value can
        only reduce the result, never increase it above base_risk_pct.
    """
    base = base_risk_pct if base_risk_pct is not None else RISK_PCT_PER_TRADE
    base = max(0.0, base)

    multiplier = _VERDICT_MULTIPLIER.get(decision.verdict, 0.0)
    size_pct = base * multiplier

    if declared_max_size_pct is not None:
        try:
            veto_cap = float(declared_max_size_pct)
        except (TypeError, ValueError):
            veto_cap = None
        if veto_cap is not None and veto_cap >= 0:
            size_pct = min(size_pct, veto_cap)

    verdict = decision.verdict
    action = decision.action
    entry = decision.entry
    stop = decision.stop
    targets = decision.targets
    if size_pct <= 0:
        size_pct = 0.0
        verdict = Verdict.REJECT
        if action in (Action.BUY, Action.SELL):
            action = Action.HOLD
            entry = None
            stop = None
            targets = ()

    return dataclasses.replace(
        decision,
        size_pct=size_pct,
        verdict=verdict,
        action=action,
        entry=entry,
        stop=stop,
        targets=targets,
    )
