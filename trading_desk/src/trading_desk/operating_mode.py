"""Phase 0 paper-only application boundary.

This is the single authoritative gate that decides whether a live order is
allowed to happen. It intentionally ignores `DESK_ALLOW_LIVE_ORDERS` and any
other environment variable: during Phase 0 (invite-only paper beta) live
execution is unreachable regardless of configuration, CLI flags, or legacy
env toggles. A future promotion decision replaces this guard; it is not
something a flag or .env value can flip on its own.

Every adapter that can place a real order (MT5 terminal connect, the
Binance Node bridge subprocess) must call `require_paper_mode` before doing
anything else — before connecting, before spawning a process, before
touching risk state. That ordering is what the TA-002 tests pin: rejection
happens before any side effect, not merely before the final "submit" call.
"""

from __future__ import annotations


class PaperOnlyError(RuntimeError):
    """Raised when a caller asks for live execution during Phase 0."""


def require_paper_mode(*, live_requested: bool) -> None:
    """Raise PaperOnlyError if `live_requested` is true.

    Deliberately takes no environment/config input: the answer for Phase 0
    is always "no live", independent of DESK_ALLOW_LIVE_ORDERS or any other
    variable a caller might set.
    """
    if live_requested:
        raise PaperOnlyError(
            "Phase 0 is paper-only. Live and demo execution require a future "
            "promotion decision (see docs/TRACKER.md Gate E7)."
        )
