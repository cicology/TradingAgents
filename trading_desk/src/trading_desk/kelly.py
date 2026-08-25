"""Kelly criterion sizing. Half-Kelly by default; cap so estimation error cannot blow the book.

f* = (p * b - q) / b
where p = win rate, q = 1-p, b = avg_win / avg_loss.

Full Kelly assumes you know p and b. We do not, so the desk uses fractional Kelly
and a hard cap (Thorp / Lo). LLM confidence is not a win rate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class KellyResult:
    full: float
    fractional: float
    capped: float
    fraction_of_full: float
    cap: float
    win_rate: float
    reward_risk: float
    edge: bool


def kelly_fraction(win_rate: float, reward_risk_ratio: float) -> float:
    p = float(win_rate)
    b = float(reward_risk_ratio)
    if b <= 0 or p <= 0 or p >= 1:
        return 0.0
    q = 1.0 - p
    raw = (p * b - q) / b
    return max(0.0, raw)


def size_position(
    win_rate: float,
    reward_risk_ratio: float,
    *,
    fraction_of_full: float = 0.5,
    cap: float = 0.05,
) -> KellyResult:
    """Return capital fractions (0-1). Default is half-Kelly, capped at 5%."""
    full = kelly_fraction(win_rate, reward_risk_ratio)
    frac = max(0.0, min(1.0, float(fraction_of_full)))
    ceiling = max(0.0, min(0.25, float(cap)))
    fractional = full * frac
    capped = min(fractional, ceiling)
    return KellyResult(
        full=full,
        fractional=fractional,
        capped=capped,
        fraction_of_full=frac,
        cap=ceiling,
        win_rate=win_rate,
        reward_risk=reward_risk_ratio,
        edge=full > 0,
    )


def shrink_confidence_to_win_rate(confidence: Any) -> float:
    """Map 0-100 model confidence to a shrunk p. Never treat 80% 'sure' as 80% win rate."""
    try:
        c = max(0.0, min(100.0, float(confidence))) / 100.0
    except (TypeError, ValueError):
        return 0.52
    return 0.50 + 0.12 * (2.0 * c - 1.0)


def reward_risk_from_decision(block: dict[str, Any], default: float = 2.0) -> float:
    try:
        entry = float(block.get("entry"))
        stop = float(block.get("stop"))
    except (TypeError, ValueError):
        return default
    risk = abs(entry - stop)
    if risk <= 0:
        # ATR-style stop stored as a distance, not a price
        if stop > 0 and entry > 0 and stop < entry * 0.2:
            risk = stop
        else:
            return default
    targets = block.get("targets") or []
    rewards: list[float] = []
    for target in targets:
        try:
            rewards.append(abs(float(target) - entry))
        except (TypeError, ValueError):
            continue
    if not rewards:
        return default
    return max(default * 0.5, rewards[0] / risk)


def size_for_trade(block: dict[str, Any], *, fraction_of_full: float, cap: float) -> KellyResult:
    p = shrink_confidence_to_win_rate(block.get("confidence"))
    b = reward_risk_from_decision(block)
    return size_position(p, b, fraction_of_full=fraction_of_full, cap=cap)
