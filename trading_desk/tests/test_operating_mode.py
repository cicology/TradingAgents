"""TA-002: the paper-only boundary is authoritative and cannot be bypassed
by CLI flags or environment variables during Phase 0.
"""

from __future__ import annotations

import pytest

from trading_desk.operating_mode import PaperOnlyError, require_paper_mode


def test_paper_request_is_allowed() -> None:
    require_paper_mode(live_requested=False)


def test_live_request_is_rejected_even_when_legacy_env_is_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DESK_ALLOW_LIVE_ORDERS", "1")

    with pytest.raises(PaperOnlyError, match="Phase 0 is paper-only"):
        require_paper_mode(live_requested=True)


def test_live_request_is_rejected_with_no_env_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DESK_ALLOW_LIVE_ORDERS", raising=False)

    with pytest.raises(PaperOnlyError):
        require_paper_mode(live_requested=True)


@pytest.mark.parametrize("env_value", ["1", "true", "TRUE", "yes"])
def test_no_env_value_can_flip_live_requested_false_into_a_live_order(
    env_value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guard must never read DESK_ALLOW_LIVE_ORDERS itself — only the
    explicit live_requested argument decides. This pins that the guard is
    not an env-var gate in disguise."""
    monkeypatch.setenv("DESK_ALLOW_LIVE_ORDERS", env_value)

    require_paper_mode(live_requested=False)
