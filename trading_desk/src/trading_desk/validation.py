"""TA-103: strict decision validator.

Turns a raw LLM/agent proposal dict into a canonical, unsized
`TradeDecision`, or raises `ValidationError` — never a best-effort guess.
Checks here are deterministic and venue/LLM-agnostic: action/verdict
vocabulary, market-snapshot freshness, spread sanity, and stop/target
direction consistency. This module does not size a trade — TA-104's
deterministic sizing takes an unsized decision from here and produces the
final, sized one. Keeping validation and sizing separate means a rejected
proposal never reaches sizing math at all.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from trading_desk.domain import Action, MarketSnapshot, TradeDecision, ValidationError, Verdict

_ALLOWED_ACTIONS = {a.value for a in Action}
_ALLOWED_VERDICTS = {v.value for v in Verdict}

# Freshness budget by research horizon. A snapshot older than this cannot
# be trusted for that horizon's decision, regardless of what the proposal
# says. Unknown horizons get the most conservative (shortest) budget.
_MAX_SNAPSHOT_AGE_SECONDS = {
    "15m": 5 * 60,
    "1h": 20 * 60,
    "swing": 30 * 60,
}
_DEFAULT_MAX_AGE_SECONDS = 5 * 60

# A spread wider than this fraction of last_close is treated as bad/stale
# data rather than a real quote — no liquid instrument in the desk's
# universe legitimately trades an 8% spread.
_MAX_SPREAD_FRACTION = 0.05


def _reject(message: str) -> None:
    raise ValidationError(message)


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_atr_style_distance(value: float, reference_price: float) -> bool:
    return 0 < value < reference_price * 0.2


def validate_decision(
    raw: dict[str, Any],
    *,
    instrument: str,
    strategy_version: str,
    market: MarketSnapshot,
    horizon: str = "swing",
    now: datetime | None = None,
) -> TradeDecision:
    now = now or datetime.now(timezone.utc)

    action_raw = raw.get("action")
    if action_raw not in _ALLOWED_ACTIONS:
        _reject(f"unsupported action: {action_raw!r}")
    action = Action(action_raw)

    verdict_raw = raw.get("verdict")
    if verdict_raw not in _ALLOWED_VERDICTS:
        _reject(f"unsupported verdict: {verdict_raw!r}")
    verdict = Verdict(verdict_raw)

    max_age = _MAX_SNAPSHOT_AGE_SECONDS.get(horizon, _DEFAULT_MAX_AGE_SECONDS)
    age = market.age_seconds(now=now)
    if age > max_age:
        _reject(f"stale market snapshot: {age:.0f}s old, max {max_age}s for horizon {horizon!r}")

    spread = market.spread()
    reference_price = market.last_close or market.ask or market.bid
    if spread is not None and reference_price:
        spread_fraction = spread / reference_price
        if spread_fraction > _MAX_SPREAD_FRACTION:
            _reject(f"spread too wide to trust: {spread_fraction:.2%} of reference price")

    rationale = str(raw.get("rationale") or raw.get("summary") or "")
    model = raw.get("_model")

    if action == Action.HOLD or verdict == Verdict.REJECT:
        return TradeDecision(
            instrument=instrument,
            strategy_version=strategy_version,
            action=action,
            verdict=Verdict.REJECT if action == Action.HOLD else verdict,
            size_pct=0.0,
            entry=None,
            stop=None,
            targets=(),
            rationale=rationale,
            model=model,
            generated_at=now,
        )

    entry = _parse_float(raw.get("entry"))
    stop = _parse_float(raw.get("stop"))
    if entry is None:
        _reject("directional proposal missing a numeric entry")
    if stop is None:
        _reject("directional proposal missing a numeric stop")

    reference = entry if entry else reference_price
    if reference and not _is_atr_style_distance(stop, reference):
        valid_side = (action == Action.BUY and stop < entry) or (action == Action.SELL and stop > entry)
        if not valid_side:
            _reject(
                f"contradictory stop: a {action.value} stop must sit on the loss side of entry, "
                f"got entry={entry} stop={stop}"
            )

    raw_targets = raw.get("targets") or []
    targets: list[float] = []
    for value in raw_targets:
        parsed = _parse_float(value)
        if parsed is None:
            continue
        valid_side = (action == Action.BUY and parsed > entry) or (action == Action.SELL and parsed < entry)
        if not valid_side:
            _reject(
                f"contradictory target: a {action.value} target must sit on the profit side of entry, "
                f"got entry={entry} target={parsed}"
            )
        targets.append(parsed)

    return TradeDecision(
        instrument=instrument,
        strategy_version=strategy_version,
        action=action,
        verdict=verdict,
        size_pct=0.0,
        entry=entry,
        stop=stop,
        targets=tuple(targets),
        rationale=rationale,
        model=model,
        generated_at=now,
    )
