# Oryares Delivery Tracker

Last updated: 2026-09-03

Repository acceptance criteria are canonical. Notion mirrors this tracker for daily workflow. Status values are `Backlog`, `Ready`, `In Progress`, `Review`, `Verified`, and `Blocked`. An item becomes `Verified` only when its evidence is linked.

[Open the Notion project hub and delivery tracker](https://app.notion.com/p/3cf2260a55dd8147b8f1ef6a00ecf743?pvs=204).

## Current Gate

**Phase 0 — Lock and baseline: E0 verified 2026-09-03 (commit range `3b39fac`..`9aca5e2`).**

Phase 0 is complete when the offline test suite passes and no public CLI path can submit a live order. As of TA-001–TA-009, all nine E0 exit-criteria items are met: live execution is unreachable (paper-only gate in `operating_mode.py`, independently enforced in the Node bridge); every sizing route (MT5 lots, Binance quantity) is deterministic and shared; the risk agent's declared cap and the desk's own Kelly cap both bound size, with the tighter one always winning; a missing or wrong-side stop fails closed instead of routing with `sl=0`; minimum-volume rounding is floor-only and rejects rather than inflates; a failed `order_check()` no longer records a paper position open; `record_close()` has an operator-facing caller and shared risk state is written atomically; the full offline suite (57 tests) passes; root CI runs it on every push/PR; and the operator/verification runbook (`docs/RUNBOOK.md`) is current. **Phase 1 (data and ledger, Gate E1) has not started.**

The [productization readiness assessment](productization/PRODUCTIZATION_READINESS_2026-09-03.md) currently rates the invite-only paper beta at **18% ready**. Public paid research is **10% ready** and customer-facing live automation is **5% ready**. These scores are planning estimates, not test coverage.

## Productization Gate Overlay

| Epic | Exit evidence | Status | Release blocker |
|---|---|---|---|
| E0 Safety isolation | Live paths unreachable; risk invariants green | Verified | Yes |
| E1 Data and ledger | Reproducible run and complete trade lifecycle | Backlog | Yes |
| E2 Evaluation | Leakage-safe backtest and walk-forward report | Backlog | Yes |
| E3 Paper broker | Deterministic fills, restart, and reconciliation tests | Backlog | Yes |
| E4 Product surface | Auth, tenant isolation, audit/export/delete E2E | Backlog | Yes |
| E5 Operations | CI/CD, observability, restore, rollback, incident drill | Backlog | Yes |
| E6 Commercial/compliance | Counsel sign-off and payment-provider approval | Backlog | Yes |
| E7 Demo/live | Broker certification, demo evidence, kill-switch drill | Backlog | Live only |

## Work Items

| ID | Phase | Work item | Status | Priority | Scope | Safety-critical | Depends on | Acceptance evidence |
|---|---:|---|---|---|---|---|---|---|
| TA-001 | 0 | Add pytest foundation and characterization fixtures | Verified | P0 | Platform | Yes | — | `PYTHONPATH=trading_desk/src python -m pytest trading_desk/tests -q` — 2 passed, 2026-09-03, commit `3b39fac`. Root CI (`.github/workflows/ci.yml`) runs compile + pytest + universe smoke on push/PR. |
| TA-002 | 0 | Enforce paper-only mode at application boundary | Verified | P0 | Platform | Yes | TA-001 | `operating_mode.require_paper_mode()` is the single authoritative gate, called first in `mt5_broker.place_order` and `binance_bridge.paper_order`, and independently hard-disabled in `integrations/binance-bridge/cli.mjs`; ignores `DESK_ALLOW_LIVE_ORDERS`. 16 tests pass (`--live`, `--mt5-live`, and env-var bypass attempts all fail closed before any adapter side effect). Commit `a6adae5`. |
| TA-003 | 0 | Honor decision and risk maximum-size caps | Verified | P0 | Platform | Yes | TA-001 | `pipeline._normalize_decision` now takes `min(KELLY_CAP, declared_max_size_pct)` before sizing; missing/non-numeric/negative `max_size_pct` is treated as zero (reject), never as unlimited. 5 tests in `test_pipeline.py`; full suite 21 passed. Commit `d08d346`. |
| TA-004 | 0 | Correct MT5 stop-price and stop-distance translation | Verified | P0 | XAU/FX | Yes | TA-001 | `_stop_distance(decision, action, tick, info)` is direction-aware (BUY stop must be below ask, SELL above bid) and rejects (`None`) a missing or wrong-side stop instead of guessing; `place_order` now refuses to route an order with no valid stop rather than falling back to sl=0. Fixtures cover XAU/USD, a 5-digit FX major, and a JPY-quoted major. 8 stop-translation tests pass. Commit `ed5ad07`. |
| TA-005 | 0 | Reject unsafe MT5 minimum-volume rounding | Verified | P0 | XAU/FX | Yes | TA-004 | `_normalize_volume` floors to the broker step and returns `None` (never bumps up to `volume_min`) when the floored size is still below minimum; `place_order` treats `None` as `status="skipped"`. 5 volume/integration tests pass, incl. a place_order-level test proving a tiny risk budget is rejected rather than inflated. Commit `ed5ad07`. |
| TA-006 | 0 | Add explicit close and shared-state reconciliation | Verified | P0 | Platform | Yes | TA-001 | `risk.check_order` now blocks any existing position on a venue+symbol (not just same-side), preventing a same-key opposite-side order from silently overwriting the tracked position. `record_open` persists approved `size_pct`. `_save_state` writes via temp-file + atomic replace. Added `desk risk close <venue> <symbol> --realized-pnl-pct` so `record_close()` has an operator-facing caller. 10 tests pass. Commit `362cad5`. |
| TA-007 | 0 | Enforce risk-aware Binance quantities | Verified | P0 | BTC | Yes | TA-001, TA-003 | Added `quantity_from_risk()`: sizes from equity/stop distance, clips to the shared `MAX_POSITION_PCT` cap, floors (never rounds up) to an exchange step, and rejects (never inflates) below minQty/minNotional. `desk binance order` and `desk brue run --paper-order` no longer accept a raw quantity — both now require `--equity`/entry/stop and compute quantity through this function. 11 tests pass (`test_binance_bridge.py`, `test_cli_binance_order.py`). Commit `0129d91`. |
| TA-008 | 0 | Publish Phase 0 operator and verification runbook | Verified | P1 | Platform | No | TA-002–TA-007 | `docs/RUNBOOK.md` published: setup, env vars (no secrets), paper-only guarantee + bypass verification checklist, test/CI commands, market-data limits, recovery/incident/rollback procedures, and known limitations. All 5 bypass-checklist commands re-run manually and confirmed to fail closed before any adapter side effect. Full gate re-verified: compile OK, 57 tests passed, `universe` and `--help` OK. Commit `9aca5e2`. |
| TA-009 | 0 | Honor MT5 order_check() before recording a paper position open | Verified | P0 | XAU/FX | Yes | TA-004, TA-005 | Discovered during E0 verification pass (mission-listed known gap: "Paper MT5 may record a position as open even when order_check fails"), not originally itemized. `place_order` now treats a non-`TRADE_RETCODE_DONE` `order_check()` result as `status="rejected"` and never calls `record_open`. 2 tests pass (`test_mt5_order_check_gate.py`). Commit `9aca5e2`. |
| TA-101 | 1 | Define canonical domain models | Backlog | P0 | Platform | Yes | Phase 0 | Model validation tests pass |
| TA-102 | 1 | Add SQLite migrations and repository boundary | Backlog | P0 | Platform | Yes | TA-101 | Fresh and upgraded databases pass migration tests |
| TA-103 | 1 | Implement strict decision validator | Backlog | P0 | Platform | Yes | TA-101 | Invalid stops, targets, expiry, and stale evidence fail closed |
| TA-104 | 1 | Implement deterministic stop-risk sizing | Backlog | P0 | Platform | Yes | TA-101, TA-103 | Accepted loss stays within configured risk under rounding |
| TA-105 | 1 | Add immutable safety and lifecycle events | Backlog | P0 | Platform | Yes | TA-102 | Retry and transaction tests prove event integrity |
| TA-201 | 2 | Ingest closed XAU/USD 4h and daily MT5 data | Backlog | P0 | XAU swing | Yes | Phase 1 | Closed-bar, freshness, and idempotency tests pass |
| TA-202 | 2 | Store versioned XAU evidence and signals | Backlog | P0 | XAU swing | Yes | TA-201 | Replayed decision has identical evidence hash |
| TA-203 | 2 | Implement paper order and fill simulator | Backlog | P0 | XAU swing | Yes | TA-202 | Fixture fills include spread, slippage, and commission |
| TA-204 | 2 | Implement position, stop, target, expiry, and close lifecycle | Backlog | P0 | XAU swing | Yes | TA-203 | Candle replay produces expected conservative outcome |
| TA-205 | 2 | Export daily equity and trade outcomes | Backlog | P1 | XAU swing | No | TA-204 | Report totals match ledger queries |
| TA-301 | 3 | Implement net performance and risk metrics | Backlog | P0 | Evaluation | No | Phase 2 | Fixture metrics match hand-calculated values |
| TA-302 | 3 | Add deterministic non-AI baseline | Backlog | P0 | Evaluation | No | TA-301 | Baseline is versioned and reproducible |
| TA-303 | 3 | Add chronological walk-forward partitions | Backlog | P0 | Evaluation | Yes | TA-301 | Tests prove evaluation rows postdate training rows |
| TA-304 | 3 | Generate promotion gate report | Backlog | P0 | Evaluation | Yes | TA-301–TA-303 | Each gate links its source metric and pass/fail reason |
| TA-401 | 4 | Add BTC/USD Binance adapter | Backlog | P1 | BTC | Yes | Phase 3 | Shared adapter contract suite passes |
| TA-402 | 4 | Add EUR/USD, GBP/USD, and USD/JPY MT5 mappings | Backlog | P1 | FX | Yes | Phase 3 | Shared adapter and contract metadata tests pass |
| TA-403 | 4 | Add independent intraday program | Backlog | P1 | All | Yes | TA-401, TA-402 | Metrics and positions remain isolated by horizon/version |
| TA-404 | 4 | Enforce portfolio and signed USD-bucket exposure | Backlog | P0 | Portfolio | Yes | TA-403 | Correlated-order fixtures are rejected at the configured cap |
| TA-501 | 5 | Add idempotent scheduler and retries | Backlog | P1 | Operations | Yes | Phase 4 | Retry tests create no duplicate signal/order/fill |
| TA-502 | 5 | Add position and ledger reconciliation | Backlog | P0 | Operations | Yes | TA-501 | Mismatch disables new orders and emits critical event |
| TA-503 | 5 | Add health checks and operator alerts | Backlog | P1 | Operations | Yes | TA-501 | Failure fixtures emit actionable, deduplicated alerts |
| TA-504 | 5 | Add database backup and restore runbook | Backlog | P1 | Operations | Yes | TA-102 | Restore drill reproduces ledger checksum |
| TA-505 | 5 | Run evidence window | Backlog | P0 | All | No | TA-501–TA-504 | Candidate has ≥100 trades and ≥90 days with frozen versions |
| TA-601 | 6 | Produce candidate promotion review | Backlog | P0 | Candidate | Yes | TA-304, TA-505 | All gates carry linked evidence and operator decision |
| TA-602 | 6 | Enable one approved candidate on demo/testnet | Backlog | P0 | Candidate | Yes | TA-601 | Only approved instrument/version/horizon can execute |
| TA-603 | 6 | Reconcile paper versus demo execution | Backlog | P0 | Candidate | Yes | TA-602 | Critical deviation automatically disables demo execution |

## Decision Log

| Date | Decision | Reason |
|---|---|---|
| 2026-09-02 | Paper-first operating mode | Edge and safety must be demonstrated before broker execution |
| 2026-09-02 | Initial cohort is XAU/USD, BTC/USD, EUR/USD, GBP/USD, USD/JPY | Covers metals, crypto, and liquid USD FX without full-universe sprawl |
| 2026-09-02 | Intraday and swing are independent programs | Prevents one horizon from masking another’s results |
| 2026-09-02 | Evidence-first promotion gate | Requires ≥100 closed trades, ≥90 days, cost-adjusted edge, controlled drawdown, and no critical safety violations |
| 2026-09-02 | Repository is canonical; Notion mirrors delivery state | Keeps acceptance criteria version-controlled while supporting daily planning |
| 2026-09-03 | First external product is Oryares Lab, invite-only and paper-only | Competing on auditability and promotion discipline is more defensible than generic AI automation |
| 2026-09-03 | RAG, GSAP, and payments are not Phase 0 dependencies | Retrieval lacks a justified corpus, animation lacks a frontend, and payment integration requires perimeter and provider approval |
| 2026-09-03 | Added TA-009 (honor MT5 `order_check()` before recording a paper open) mid-phase, outside the original TA-001–008 itemization | Confirmed during E0 verification against the mission's known-gaps list; `record_open` was unconditional in the paper path regardless of `order_check` retcode |
| 2026-09-03 | git push to `origin/oryares-desk` is blocked: `Permission to cicology/TradingAgents.git denied to Cico-hub` (403) | Credentials/authorization issue outside engineering scope; all Phase 0 work is committed locally and ready to push once access is restored |
