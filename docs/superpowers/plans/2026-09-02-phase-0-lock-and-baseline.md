# Phase 0 Lock and Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the current desk provably paper-only, establish an offline regression suite, and correct the known execution-safety defects before the new ledger architecture is introduced.

**Architecture:** Preserve the current CLI and adapter structure while adding a single operating-mode boundary and test seams around risk and broker translation. Phase 0 deliberately avoids the Phase 1 SQLite/domain-model rebuild; it makes the existing system safe and characterized so that later replacement is controlled.

**Tech Stack:** Python 3.11+, pytest, standard-library dataclasses/pathlib/json, existing MetaTrader5 and Node bridge adapters

---

## File Map

- Create `trading_desk/tests/conftest.py`: shared fixtures and import setup.
- Create `trading_desk/tests/test_operating_mode.py`: paper-only invariant tests.
- Create `trading_desk/tests/test_pipeline.py`: decision cap regression tests.
- Create `trading_desk/tests/test_mt5_broker.py`: stop and minimum-volume regression tests.
- Create `trading_desk/tests/test_risk.py`: persistent shared-risk lifecycle tests.
- Create `trading_desk/tests/test_binance_bridge.py`: risk-sized order boundary tests.
- Create `trading_desk/src/trading_desk/operating_mode.py`: authoritative Phase 0 paper lock.
- Modify `trading_desk/pyproject.toml`: test dependency and pytest configuration.
- Modify `trading_desk/src/trading_desk/cli.py`: reject live flags and add explicit risk close command.
- Modify `trading_desk/src/trading_desk/pipeline.py`: enforce the tightest declared maximum size.
- Modify `trading_desk/src/trading_desk/mt5_broker.py`: enforce paper mode and safe stop/volume conversion.
- Modify `trading_desk/src/trading_desk/binance_bridge.py`: remove arbitrary-quantity risk bypass.
- Modify `integrations/binance-bridge/cli.mjs`: hard-disable live submission in Phase 0.
- Modify `trading_desk/src/trading_desk/risk.py`: atomic state, any-position duplicate prevention, and explicit close lifecycle.
- Modify `docs/TRADING_DESK.md`: Phase 0 operator behavior and test command.
- Modify `docs/TRACKER.md`: move work items only when acceptance evidence exists.

### Task 1: TA-001 — Establish the Offline Test Foundation

**Files:**
- Modify: `trading_desk/pyproject.toml`
- Create: `trading_desk/tests/conftest.py`
- Create: `trading_desk/tests/test_current_behavior.py`

- [ ] **Step 1: Add the test dependency and configuration**

Add to `trading_desk/pyproject.toml`:

```toml
[project.optional-dependencies]
test = [
    "pytest>=8.3,<9",
]

[tool.pytest.ini_options]
addopts = "-ra"
testpaths = ["tests"]
```

- [ ] **Step 2: Add deterministic shared fixtures**

Create `trading_desk/tests/conftest.py`:

```python
from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.fixture
def mt5_info() -> SimpleNamespace:
    return SimpleNamespace(
        point=0.01,
        trade_contract_size=100.0,
        trade_tick_size=0.01,
        trade_tick_value=1.0,
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
    )


@pytest.fixture
def gold_tick() -> SimpleNamespace:
    return SimpleNamespace(bid=2499.90, ask=2500.10)
```

- [ ] **Step 3: Characterize current dry-run behavior**

Create `trading_desk/tests/test_current_behavior.py`:

```python
from trading_desk.agents import heuristic_decision
from trading_desk.pipeline import _normalize_decision


def test_dry_run_is_rejected_and_zero_sized() -> None:
    market = {"daily": {"last_close": 2500.0, "rsi_14": 30.0, "macd_hist": 1.0, "atr_14": 25.0}}

    decision = _normalize_decision(heuristic_decision(market))

    assert decision["action"] == "BUY"
    assert decision["verdict"] == "REJECT"
    assert decision["size_pct"] == 0.0
```

- [ ] **Step 4: Install test dependencies and run the characterization test**

Run:

```powershell
python -m pip install -e "trading_desk[test]"
python -m pytest trading_desk/tests/test_current_behavior.py -v
```

Expected: one passing test and no network access.

- [ ] **Step 5: Commit the test foundation**

```powershell
git add trading_desk/pyproject.toml trading_desk/tests/conftest.py trading_desk/tests/test_current_behavior.py
git commit -m "test: establish desk regression suite"
```

### Task 2: TA-002 — Enforce Paper-Only Operation

**Files:**
- Create: `trading_desk/src/trading_desk/operating_mode.py`
- Create: `trading_desk/tests/test_operating_mode.py`
- Modify: `trading_desk/src/trading_desk/cli.py`
- Modify: `trading_desk/src/trading_desk/mt5_broker.py`
- Modify: `trading_desk/src/trading_desk/binance_bridge.py`
- Modify: `integrations/binance-bridge/cli.mjs`

- [ ] **Step 1: Write failing paper-lock tests**

Create `trading_desk/tests/test_operating_mode.py`:

```python
import pytest

from trading_desk.operating_mode import PaperOnlyError, require_paper_mode


def test_paper_request_is_allowed() -> None:
    require_paper_mode(live_requested=False)


def test_live_request_is_rejected_even_when_legacy_env_is_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DESK_ALLOW_LIVE_ORDERS", "1")

    with pytest.raises(PaperOnlyError, match="Phase 0 is paper-only"):
        require_paper_mode(live_requested=True)
```

- [ ] **Step 2: Run the tests and verify the missing module failure**

Run:

```powershell
python -m pytest trading_desk/tests/test_operating_mode.py -v
```

Expected: collection fails because `trading_desk.operating_mode` does not exist.

- [ ] **Step 3: Implement the authoritative operating-mode guard**

Create `trading_desk/src/trading_desk/operating_mode.py`:

```python
from __future__ import annotations


class PaperOnlyError(RuntimeError):
    pass


def require_paper_mode(*, live_requested: bool) -> None:
    if live_requested:
        raise PaperOnlyError(
            "Phase 0 is paper-only. Live and demo execution require a future promotion decision."
        )
```

- [ ] **Step 4: Apply the guard before every adapter side effect**

In both `mt5_broker.place_order` and `binance_bridge.paper_order`, call the guard before connection or subprocess invocation:

```python
from trading_desk.operating_mode import require_paper_mode

require_paper_mode(live_requested=live)
```

In `cli.main`, reject `--mt5-live` and `binance order --live` through the same exception path. Keep the flags temporarily so existing scripts receive a clear failure instead of an argument-parsing surprise.

- [ ] **Step 5: Hard-disable the Node submission path**

Replace the live branch in `integrations/binance-bridge/cli.mjs` with:

```javascript
if (live) {
  fail("Phase 0 is paper-only. The Binance bridge cannot submit orders.");
}
ok({ ...intended, status: "paper-logged" });
return;
```

This second boundary prevents direct Node invocation from bypassing Python.

- [ ] **Step 6: Verify the invariant**

Run:

```powershell
python -m pytest trading_desk/tests/test_operating_mode.py -v
rg -n "submitNewOrder|order_send" trading_desk/src integrations/binance-bridge/cli.mjs
```

Expected: tests pass. `submitNewOrder` is absent from the bridge; `order_send` may remain in MT5 code but is unreachable because the guard rejects `live=True` before connecting.

- [ ] **Step 7: Commit the paper lock**

```powershell
git add trading_desk/src/trading_desk/operating_mode.py trading_desk/src/trading_desk/cli.py trading_desk/src/trading_desk/mt5_broker.py trading_desk/src/trading_desk/binance_bridge.py integrations/binance-bridge/cli.mjs trading_desk/tests/test_operating_mode.py
git commit -m "safety: enforce paper-only operating mode"
```

### Task 3: TA-003 — Enforce the Tightest Decision Cap

**Files:**
- Create: `trading_desk/tests/test_pipeline.py`
- Modify: `trading_desk/src/trading_desk/pipeline.py`

- [ ] **Step 1: Write failing cap tests**

Create `trading_desk/tests/test_pipeline.py`:

```python
from trading_desk.pipeline import _normalize_decision


def proposal(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "action": "BUY",
        "verdict": "APPROVE",
        "confidence": 80,
        "entry": 100.0,
        "stop": 95.0,
        "targets": [110.0],
        "max_size_pct": 1.0,
    }
    value.update(overrides)
    return value


def test_risk_maximum_caps_computed_size() -> None:
    decision = _normalize_decision(proposal())
    assert decision["size_pct"] <= 1.0
    assert decision["max_size_pct"] == 1.0


def test_zero_risk_maximum_rejects_directional_trade() -> None:
    decision = _normalize_decision(proposal(max_size_pct=0))
    assert decision["verdict"] == "REJECT"
    assert decision["size_pct"] == 0.0
```

- [ ] **Step 2: Run the tests and verify failure**

Run:

```powershell
python -m pytest trading_desk/tests/test_pipeline.py -v
```

Expected: at least the 1% cap assertion fails against current normalization.

- [ ] **Step 3: Apply the tightest cap**

Add to `pipeline.py`:

```python
def _pct(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, parsed)
```

In `_normalize_decision`, calculate the effective fraction before `size_for_trade`:

```python
declared_cap_pct = _pct(block.get("max_size_pct"), KELLY_CAP * 100.0)
effective_cap = min(KELLY_CAP, declared_cap_pct / 100.0)
kelly = size_for_trade(block, fraction_of_full=frac, cap=effective_cap)
```

If `effective_cap == 0`, set `verdict` to `REJECT`. Preserve this as an interim safety fix; Phase 1 removes LLM-confidence Kelly sizing entirely.

- [ ] **Step 4: Run focused and complete tests**

Run:

```powershell
python -m pytest trading_desk/tests/test_pipeline.py -v
python -m pytest trading_desk/tests -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit the cap fix**

```powershell
git add trading_desk/src/trading_desk/pipeline.py trading_desk/tests/test_pipeline.py
git commit -m "fix: enforce risk decision size cap"
```

### Task 4: TA-004 and TA-005 — Correct MT5 Stop and Volume Safety

**Files:**
- Create: `trading_desk/tests/test_mt5_broker.py`
- Modify: `trading_desk/src/trading_desk/mt5_broker.py`

- [ ] **Step 1: Write failing stop-translation tests**

Create `trading_desk/tests/test_mt5_broker.py`:

```python
import pytest

from trading_desk.mt5_broker import _normalize_volume, _stop_distance


def test_buy_price_stop_becomes_distance(gold_tick, mt5_info) -> None:
    decision = {"entry": 2500.0, "stop": 2475.0}
    assert _stop_distance(decision, "BUY", gold_tick, mt5_info) == pytest.approx(25.1)


def test_sell_price_stop_becomes_distance(gold_tick, mt5_info) -> None:
    decision = {"entry": 2500.0, "stop": 2525.0}
    assert _stop_distance(decision, "SELL", gold_tick, mt5_info) == pytest.approx(25.1)


def test_atr_distance_is_preserved(gold_tick, mt5_info) -> None:
    decision = {"entry": 2500.0, "stop": 25.0}
    assert _stop_distance(decision, "BUY", gold_tick, mt5_info) == 25.0


def test_stop_on_wrong_side_is_rejected(gold_tick, mt5_info) -> None:
    decision = {"entry": 2500.0, "stop": 2525.0}
    assert _stop_distance(decision, "BUY", gold_tick, mt5_info) is None


def test_volume_below_minimum_is_not_rounded_up(mt5_info) -> None:
    assert _normalize_volume(mt5_info, 0.004) is None


def test_volume_rounds_down_to_preserve_risk(mt5_info) -> None:
    assert _normalize_volume(mt5_info, 0.019) == 0.01
```

- [ ] **Step 2: Run tests and verify signature and behavior failures**

Run:

```powershell
python -m pytest trading_desk/tests/test_mt5_broker.py -v
```

Expected: current `_stop_distance` signature and volume rounding fail.

- [ ] **Step 3: Implement direction-aware stop parsing**

Replace `_stop_distance` with direction-aware behavior:

```python
def _stop_distance(decision: dict[str, Any], action: str, tick: Any, info: Any) -> float | None:
    try:
        stop = float(decision["stop"])
    except (KeyError, TypeError, ValueError):
        return None
    price = float(tick.ask if action == "BUY" else tick.bid)
    if not price or stop <= 0:
        return None
    if stop < price * 0.2:
        return stop
    valid_price_stop = (action == "BUY" and stop < price) or (action == "SELL" and stop > price)
    if not valid_price_stop:
        return None
    distance = abs(price - stop)
    minimum = float(getattr(info, "point", 0.0) or 0.0)
    return distance if distance >= minimum else None
```

Change the caller to `_stop_distance(decision, action, tick, info)`.

- [ ] **Step 4: Implement risk-preserving volume normalization**

Use floor rounding and make an unsafe minimum explicit:

```python
import math


def _normalize_volume(info: Any, volume: float) -> float | None:
    step = float(info.volume_step or 0.01)
    vmin = float(info.volume_min or step)
    vmax = float(info.volume_max or volume)
    if volume < vmin:
        return None
    steps = math.floor((min(volume, vmax) + 1e-12) / step)
    sized = steps * step
    if sized < vmin:
        return None
    digits = 0 if step >= 1 else len(str(step).rstrip("0").split(".")[-1])
    return float(f"{sized:.{digits}f}")
```

In `place_order`, return `status="skipped"` and reason `broker minimum volume exceeds risk budget` when normalization returns `None`.

- [ ] **Step 5: Run regression tests**

Run:

```powershell
python -m pytest trading_desk/tests/test_mt5_broker.py -v
python -m pytest trading_desk/tests -q
```

Expected: all tests pass without importing or connecting to MetaTrader5.

- [ ] **Step 6: Commit the MT5 safety fixes**

```powershell
git add trading_desk/src/trading_desk/mt5_broker.py trading_desk/tests/test_mt5_broker.py
git commit -m "fix: preserve MT5 stop and volume risk"
```

### Task 5: TA-006 — Make Shared Position State Reconciliable

**Files:**
- Create: `trading_desk/tests/test_risk.py`
- Modify: `trading_desk/src/trading_desk/risk.py`
- Modify: `trading_desk/src/trading_desk/cli.py`

- [ ] **Step 1: Write failing lifecycle tests**

Create `trading_desk/tests/test_risk.py`:

```python
import json

import pytest

from trading_desk import risk


def test_existing_position_blocks_both_new_directions(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(risk, "STATE_PATH", tmp_path / "risk.json")
    risk.record_open("mt5", "XAUUSD", "BUY", size_pct=0.5)

    assert not risk.check_order("mt5", "XAUUSD", "BUY", 0.5).approved
    assert not risk.check_order("mt5", "XAUUSD", "SELL", 0.5).approved


def test_close_clears_position_and_updates_daily_pnl(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(risk, "STATE_PATH", tmp_path / "risk.json")
    risk.record_open("mt5", "XAUUSD", "BUY", size_pct=0.5)

    risk.record_close("mt5", "XAUUSD", realized_pnl_pct=-0.4)

    assert risk.open_positions() == {}
    breached, pnl = risk.daily_loss_breached()
    assert not breached
    assert pnl == -0.4
    assert json.loads(risk.STATE_PATH.read_text())["daily"]["realized_pnl_pct"] == -0.4
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
python -m pytest trading_desk/tests/test_risk.py -v
```

Expected: `record_open` does not accept `size_pct`, and an opposite-side duplicate is not blocked.

- [ ] **Step 3: Store risk metadata and block any unreconciled position**

Change the duplicate gate to reject any existing key:

```python
if existing:
    return RiskDecision(
        False,
        f"Position already open on {venue}:{symbol} since {existing.get('opened_at')}",
        0.0,
    )
```

Change `record_open` to accept and persist size:

```python
def record_open(venue: str, symbol: str, action: str, size_pct: float | None = None) -> None:
    action = (action or "").upper()
    if action not in {"BUY", "SELL"}:
        return
    state = _load_state()
    state.setdefault("open_positions", {})[_position_key(venue, symbol)] = {
        "side": action,
        "size_pct": size_pct,
        "opened_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_state(state)
```

Update both adapter callers to pass the approved `size_pct` when known.

- [ ] **Step 4: Make state replacement atomic**

Replace `_save_state` with a same-directory temporary write:

```python
def _save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    temporary.replace(STATE_PATH)
```

- [ ] **Step 5: Add an explicit operator close command**

Add `risk close <venue> <symbol> --realized-pnl-pct <number>` to `cli.py`. Its handler calls `record_close`, prints the closed key and recorded P&L, and never accepts a missing P&L value. This is an interim reconciliation operation until Phase 1 derives closure from lifecycle events.

- [ ] **Step 6: Verify lifecycle behavior**

Run:

```powershell
python -m pytest trading_desk/tests/test_risk.py -v
python -m pytest trading_desk/tests -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit shared-risk reconciliation**

```powershell
git add trading_desk/src/trading_desk/risk.py trading_desk/src/trading_desk/cli.py trading_desk/src/trading_desk/mt5_broker.py trading_desk/tests/test_risk.py
git commit -m "fix: reconcile shared risk position state"
```

### Task 6: TA-007 — Remove Arbitrary Binance Quantity Bypass

**Files:**
- Create: `trading_desk/tests/test_binance_bridge.py`
- Modify: `trading_desk/src/trading_desk/binance_bridge.py`
- Modify: `trading_desk/src/trading_desk/cli.py`

- [ ] **Step 1: Write failing risk-quantity tests**

Create `trading_desk/tests/test_binance_bridge.py`:

```python
import pytest

from trading_desk.binance_bridge import quantity_from_risk


def test_linear_contract_quantity_uses_stop_loss_budget() -> None:
    quantity = quantity_from_risk(equity=10_000, size_pct=0.5, entry=50_000, stop=49_000)
    assert quantity == pytest.approx(0.05)


def test_invalid_stop_direction_is_rejected() -> None:
    with pytest.raises(ValueError, match="stop must be below entry"):
        quantity_from_risk(equity=10_000, size_pct=0.5, entry=50_000, stop=51_000, side="BUY")


def test_size_above_shared_cap_is_clipped(monkeypatch: pytest.MonkeyPatch) -> None:
    quantity = quantity_from_risk(equity=10_000, size_pct=20, entry=50_000, stop=49_000)
    assert quantity == pytest.approx(0.5)
```

- [ ] **Step 2: Run tests and verify the missing function failure**

Run:

```powershell
python -m pytest trading_desk/tests/test_binance_bridge.py -v
```

Expected: import fails because `quantity_from_risk` does not exist.

- [ ] **Step 3: Implement linear USD-margined risk sizing**

Add to `binance_bridge.py`:

```python
def quantity_from_risk(
    *, equity: float, size_pct: float, entry: float, stop: float, side: str = "BUY"
) -> float:
    from trading_desk.risk import MAX_POSITION_PCT

    side = side.upper()
    if equity <= 0 or entry <= 0 or stop <= 0:
        raise ValueError("equity, entry, and stop must be positive")
    if side == "BUY" and stop >= entry:
        raise ValueError("BUY stop must be below entry")
    if side == "SELL" and stop <= entry:
        raise ValueError("SELL stop must be above entry")
    if side not in {"BUY", "SELL"}:
        raise ValueError("side must be BUY or SELL")
    approved_pct = min(max(0.0, size_pct), MAX_POSITION_PCT)
    risk_money = equity * approved_pct / 100.0
    return risk_money / abs(entry - stop)
```

This formula applies only to linear USD-margined contracts. The function name and docstring must state that boundary.

- [ ] **Step 4: Replace the CLI quantity input with risk inputs**

Change `binance order` to require `--equity`, `--entry`, `--stop`, and optional `--size-pct` defaulting to `0.5`. Calculate quantity in Python, pass the calculated value to `paper_order`, and pass `size_pct` into `check_order` and `record_open`. Remove the arbitrary positional quantity argument so it cannot bypass risk policy.

- [ ] **Step 5: Verify sizing and CLI help**

Run:

```powershell
python -m pytest trading_desk/tests/test_binance_bridge.py -v
python -m trading_desk binance order --help
python -m pytest trading_desk/tests -q
```

Expected: tests pass; help requires explicit equity, entry, and stop inputs; the full suite passes.

- [ ] **Step 6: Commit Binance risk sizing**

```powershell
git add trading_desk/src/trading_desk/binance_bridge.py trading_desk/src/trading_desk/cli.py trading_desk/tests/test_binance_bridge.py
git commit -m "fix: size Binance paper orders from risk"
```

### Task 7: TA-008 — Verify and Publish the Phase 0 Gate

**Files:**
- Modify: `docs/TRADING_DESK.md`
- Modify: `docs/TRACKER.md`
- Modify: `README.md`

- [ ] **Step 1: Run the complete offline verification suite**

Run:

```powershell
python -m compileall -q trading_desk/src
python -m pytest trading_desk/tests -q
python -m trading_desk universe
python -m trading_desk --help
```

Expected: compile succeeds, all tests pass, the universe lists supported current instruments, and CLI help exits successfully.

- [ ] **Step 2: Prove both live paths fail closed**

Run with no broker credentials:

```powershell
python -m trading_desk mt5 order gold BUY --live
python -m trading_desk binance order btc BUY --equity 10000 --entry 50000 --stop 49000 --live
node integrations/binance-bridge/cli.mjs order BTCUSDT BUY 0.001 --live
```

Expected: each command exits non-zero with `Phase 0 is paper-only`; none attempts a network or broker connection.

- [ ] **Step 3: Document the operator behavior**

Update `docs/TRADING_DESK.md` with:

```markdown
## Phase 0 safety state

The desk is paper-only. Python and the direct Node bridge reject every live request before broker or network submission. `DESK_ALLOW_LIVE_ORDERS` is ignored during Phase 0.

Run the offline gate with:

```powershell
python -m compileall -q trading_desk/src
python -m pytest trading_desk/tests -q
```
```

- [ ] **Step 4: Update tracker evidence**

In `docs/TRACKER.md`, move TA-001 through TA-008 to `Verified` only after adding the exact test command, test count, date, and commit SHA to the acceptance-evidence cells. Do not mark the phase complete if any live-path command reaches an adapter connection.

- [ ] **Step 5: Inspect the final diff and repository state**

Run:

```powershell
git diff --check
git status --short
```

Expected: no whitespace errors and only intended Phase 0 files are modified.

- [ ] **Step 6: Commit Phase 0 documentation**

```powershell
git add README.md docs/TRADING_DESK.md docs/TRACKER.md
git commit -m "docs: record verified phase 0 safety gate"
```

- [ ] **Step 7: Push the verified phase**

Run:

```powershell
git push origin oryares-desk
```

Expected: the remote branch advances to the final verified Phase 0 commit.

## Plan Self-Review

- Every Phase 0 tracker item TA-001 through TA-008 maps to a task and acceptance command.
- The paper lock exists independently in Python and the direct Node bridge.
- MT5 stop and quantity corrections have offline tests and fail closed.
- Shared position closure is explicit and auditable until the Phase 1 lifecycle ledger replaces JSON state.
- Binance manual quantity is removed rather than left as a risk bypass.
- Phase 1 architecture is not pulled prematurely into this safety phase.
