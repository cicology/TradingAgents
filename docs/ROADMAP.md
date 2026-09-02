# Oryares Delivery Roadmap

Last updated: 2026-09-02

This roadmap implements the [paper-first platform design](superpowers/specs/2026-09-02-paper-first-trading-platform-design.md). Each phase has a hard exit gate. Work may be explored early, but no dependent phase is considered active until its prerequisite gate is verified.

| Phase | Outcome | Exit gate |
|---|---|---|
| 0. Lock and baseline | Live execution disabled; current behavior characterized; known safety defects corrected | Full local test suite passes and no public CLI can submit a live order |
| 1. Trusted foundation | Typed contracts, SQLite ledger, validation, deterministic sizing, versioned risk | Transactional lifecycle and risk invariants pass offline tests |
| 2. XAU/USD swing slice | Complete 4h/daily signal-to-outcome paper loop | Fixed candle replay produces reproducible fills, exits, P&L, and reports |
| 3. Evaluation | Net metrics, baselines, walk-forward partitions, promotion report | Known fixture metrics match independently calculated expected values |
| 4. Cohort expansion | BTC and three FX majors; independent intraday programs | Every adapter passes the same contract suite and portfolio risk limits hold |
| 5. Paper operations | Scheduling, retry safety, reconciliation, health, alerts, backups | Thirty consecutive operating days without an unresolved critical safety event |
| 6. Demo promotion | Individually approved strategy runs on MT5 demo or Binance testnet | Paper gate passed, operator approved, and paper-vs-demo reconciliation is healthy |

## Phase 0 — Lock and Baseline

- Add pytest and a single documented test command.
- Capture current decision normalization, shared risk, MT5 sizing, and Binance bridge behavior.
- Add an application-boundary paper-only lock.
- Honor the risk agent’s maximum size.
- Correct MT5 stop-price versus stop-distance handling.
- Reject broker minimum volume when it exceeds permitted risk.
- Reconcile shared position state and make closing positions an explicit workflow.
- Calculate and enforce Binance order risk rather than passing an uncapped quantity.

Detailed execution steps: [Phase 0 implementation plan](superpowers/plans/2026-09-02-phase-0-lock-and-baseline.md).

## Phase 1 — Trusted Foundation

- Define focused domain models for market data, signals, risk decisions, orders, fills, and positions.
- Add SQLite schema migrations and transactional repositories.
- Add strict decision validation and immutable strategy/risk-policy versions.
- Replace LLM-confidence Kelly sizing with stop-distance risk sizing.
- Record safety events and idempotency keys.

## Phase 2 — XAU/USD Swing Vertical Slice

- Ingest closed MT5 4-hour bars and daily context.
- Store a decision-time evidence snapshot.
- Simulate spread, slippage, commission, order expiry, stop, target, and explicit exit.
- Use conservative same-bar stop/target ordering when tick sequence is unavailable.
- Produce daily equity and trade-level outcome exports.

## Phase 3 — Evaluation

- Calculate expectancy, profit factor, payoff, drawdown, cost drag, exposure, MAE, and MFE.
- Declare and implement a deterministic baseline per candidate.
- Freeze versions before chronological evaluation windows.
- Generate pass/fail promotion reports with supporting evidence.

## Phase 4 — Cohort Expansion

- Add BTC/USD via Binance.
- Add EUR/USD, GBP/USD, and USD/JPY via MT5.
- Add intraday programs as independent strategy versions.
- Aggregate signed currency exposure and enforce the USD bucket.

## Phase 5 — Paper Operations

- Schedule scans by venue session and timeframe.
- Make retries idempotent.
- Reconcile ledger state with observed market and, later, demo venue state.
- Add health checks, operator alerts, database backups, and migration rollback procedures.
- Run the evidence window for each candidate.

## Phase 6 — Demo Promotion

- Require 100 closed trades and 90 days per candidate.
- Require positive cost-adjusted expectancy, profit factor at least 1.20, drawdown at most 10%, baseline outperformance, and no unresolved critical safety event.
- Require explicit operator approval.
- Enable only the approved candidate in demo/testnet mode.
- Automatically disable demo execution on a critical safety event or reconciliation failure.

## Explicitly Deferred

- Live-capital execution
- High-frequency and sub-minute trading
- Additional instruments
- Complex portfolio optimization
- Self-modifying strategies
- A hosted dashboard before the ledger and metrics are trustworthy
