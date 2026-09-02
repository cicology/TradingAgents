# Paper-First Trading Platform Design

**Date:** 2026-09-02  
**Status:** Approved design  
**Initial cohort:** XAU/USD, BTC/USD, EUR/USD, GBP/USD, USD/JPY  
**Programs:** Intraday and swing, evaluated independently

## 1. Objective

Turn Oryares TradingAgents from an AI market-opinion prototype into a trustworthy paper-trading research platform. The platform must measure whether a versioned strategy has a repeatable edge after realistic costs before it can be considered for demo execution.

The immediate target is paper trading. Live-capital execution is outside this design and remains disabled. Promotion from paper to MT5 demo or Binance testnet requires objective evidence and a separate explicit decision.

## 2. Product Principles

1. Evidence precedes execution. Every decision must be reproducible from the market data available at its timestamp.
2. AI performs research and synthesis. It does not control position size, bypass validation, or override risk rules.
3. Risk is deterministic. Position size, portfolio limits, loss halts, spread limits, and data-freshness checks are enforced in code.
4. Paper trading models the intended venue. Gold and forex use MT5-compatible prices and contract metadata; BTC uses Binance-compatible market data and costs.
5. Intraday and swing are separate programs. They have independent strategy versions, trades, metrics, and promotion decisions.
6. Every lifecycle change is auditable. Signals, rejections, orders, fills, position changes, exits, and safety events are immutable records.
7. Nothing is promoted on narrative judgment alone. Promotion requires sufficient samples, elapsed time, positive net performance, controlled drawdown, and no unresolved critical safety violations.

## 3. Scope

### 3.1 Included

- XAU/USD
- BTC/USD
- EUR/USD
- GBP/USD
- USD/JPY
- Swing program using closed 4-hour bars with daily context
- Intraday program using closed 15-minute bars with 1-hour context
- Versioned strategies and risk policies
- Paper order, fill, position, and exit lifecycle
- Realistic spread, commission, and configurable slippage
- Portfolio and per-strategy evaluation
- Repository roadmap and tracker mirrored into Notion
- Promotion reporting for paper-to-demo decisions

### 3.2 Excluded

- Live-capital execution
- Automatic promotion to demo or live modes
- High-frequency or sub-minute strategies
- Options, prediction markets, silver, indices, and additional FX pairs in the first cohort
- LLM-derived win probabilities or position sizes
- Self-modifying strategies or risk policies

Polybot remains a separate Polymarket system. It is not part of the conventional-market execution path in this design.

## 4. Architecture

```text
Market adapters
  MT5 candles/quotes | Binance candles | optional reference feed
          |
          v
Canonical market data
  instrument, venue, timestamp, timeframe, OHLCV, spread, freshness
          |
          +-- Intraday program: 15m signal + 1h context
          +-- Swing program: 4h signal + 1d context
                         |
                         v
Evidence package
  deterministic indicators + regime + permitted news context
                         |
                         v
AI research agents
  analysis and synthesis only
                         |
                         v
Strict decision validator
  action, entry, stop, targets, horizon, expiry, evidence references
                         |
                         v
Deterministic risk engine
  trade risk, exposure, correlation, spread, freshness, loss halts
                         |
                         v
Paper execution engine
  orders, simulated fills, costs, stops, targets, expiry, closure
                         |
                         v
Immutable event ledger
  signals -> orders -> fills -> positions -> exits -> outcomes
                         |
                         v
Evaluation and promotion gates
```

Each component exposes a narrow interface and can be tested without an LLM, live broker, or network connection. Broker adapters translate canonical requests into venue-specific formats; they do not make strategy or risk decisions.

## 5. Market Data

### 5.1 Primary feeds

- XAU/USD and FX majors: MT5 candles, quotes, symbol metadata, and trading-session state. This minimizes differences between research prices and the intended demo venue.
- BTC/USD: Binance candles and quote/order-book data. Testnet is used only after paper promotion.
- Optional independent feeds may be used for anomaly detection, but the primary venue feed determines paper fills.

### 5.2 Canonical bar and quote requirements

Every record includes:

- canonical instrument ID and venue symbol
- venue and data-source identifier
- UTC open and close timestamps
- timeframe
- OHLCV values
- bid, ask, mid, and spread when available
- whether the bar is closed
- ingestion timestamp
- source timestamp and freshness status

Strategies may evaluate only closed bars. Duplicate `(instrument, venue, timeframe, close_timestamp)` records are idempotently ignored. Stale or missing primary data produces a safety event and no new signal.

## 6. Decision Contract

Each strategy decision is immutable and contains:

- decision ID
- strategy ID and semantic version
- risk-policy version
- instrument and horizon
- evidence snapshot ID
- decision timestamp and expiry
- `BUY`, `SELL`, or `HOLD`
- proposed entry or entry rule
- mandatory stop for directional decisions
- zero or more targets
- rationale and referenced evidence
- model/provider metadata when AI contributed

Validation rejects malformed types, non-finite numbers, expired decisions, stops on the wrong side of entry, targets on the wrong side, unreasonable stop distance, unavailable instruments, stale evidence, and directional decisions without calculable risk.

AI confidence is stored for later calibration analysis but does not affect order size.

## 7. Canonical Store and Audit Model

SQLite is the canonical paper-trading store. It provides transactions, constraints, migrations, reproducible queries, and simple local operation without another service. Existing JSON and Markdown reports remain exports rather than authoritative state.

Core tables:

- `schema_migrations`: applied database versions
- `market_snapshots`: immutable decision-time evidence
- `signals`: validated and rejected strategy decisions
- `orders`: paper order intent and state
- `fills`: simulated execution details and costs
- `positions`: current materialized position state
- `position_events`: immutable lifecycle events
- `daily_equity`: end-of-period equity, exposure, and drawdown
- `safety_events`: validation failures, circuit breakers, reconciliation failures, and operator actions
- `strategy_versions`: strategy configuration and source identity
- `risk_policy_versions`: complete risk settings used by each decision

All timestamps are UTC. IDs are generated before side effects. Signal processing is idempotent so retries cannot create duplicate positions. State-changing operations use database transactions.

## 8. Paper Execution Lifecycle

1. A strategy creates a decision from a stored evidence snapshot.
2. The decision validator accepts or rejects the contract.
3. The risk engine calculates permitted risk and records its decision.
4. An accepted signal becomes a paper order with an expiry.
5. The fill simulator applies venue-specific bid/ask spread, configured slippage, and commission.
6. A fill creates or changes a position and records an immutable event.
7. Closed bars or venue ticks evaluate stop, target, expiry, and explicit-exit rules.
8. A close records exit costs, realized P&L, R-multiple, holding time, and maximum favorable/adverse excursion.
9. Equity, exposure, drawdown, and promotion metrics are updated.

If stop and target are both crossed inside one bar and tick order is unavailable, the simulator uses the conservative outcome. This rule is explicit in every affected trade record.

## 9. Initial Risk Policy

- Risk per trade: 0.5% of current paper equity
- Maximum combined risk per instrument: 1.0%
- Maximum open portfolio risk: 2.0%
- Maximum correlated USD-bucket risk: 1.5%
- Realized daily-loss halt: 2.0%
- Rolling seven-day loss halt: 5.0%
- Peak-to-trough paper drawdown pause: 10.0%
- One same-direction position per instrument, strategy, and horizon
- No averaging down
- Mandatory valid stop for every directional order
- Reject stale price, excessive spread, invalid target, uncalculable risk, and unsafe broker-minimum volume
- Risk halts require an explicit recorded operator action; strategies and agents cannot reset them

Risk is calculated from entry-to-stop loss in account currency using venue contract metadata. If the minimum permitted quantity exceeds the risk budget, the order is rejected rather than rounded upward. Configuration changes create a new immutable risk-policy version.

Portfolio USD exposure uses signed currency-factor mappings. For example, long EUR/USD and long GBP/USD both express short-USD exposure, while long USD/JPY expresses long-USD exposure. Gold and BTC USD sensitivity is monitored in the same bucket but reported separately because their relationship with USD is regime-dependent.

## 10. Evaluation

Metrics are reported by instrument, strategy version, horizon, and combined portfolio:

- closed trades and elapsed evaluation days
- gross and net P&L
- expectancy in account currency and R-multiples
- profit factor
- win rate and payoff ratio
- maximum drawdown and recovery duration
- spread, slippage, and commission impact
- maximum favorable and adverse excursion
- exposure and holding time
- consecutive losses
- AI-confidence calibration, reported but never used directly for sizing
- safety-event count and severity

Each candidate is compared with a declared, reproducible non-AI baseline. Evaluation uses chronological walk-forward partitions. Parameters and prompts are frozen before the untouched evaluation window begins; results from tuning data cannot satisfy a promotion gate.

## 11. Paper-to-Demo Promotion Gate

Promotion is evaluated separately for each instrument, strategy version, and horizon. A candidate must meet all of the following:

- at least 100 closed paper trades
- at least 90 elapsed calendar days
- positive expectancy after spread, slippage, and commissions
- profit factor of at least 1.20
- maximum drawdown no greater than 10%
- better risk-adjusted performance than its declared baseline
- zero unresolved critical safety violations
- reproducible performance on an untouched evaluation window

Passing produces a reviewable promotion report; it does not enable execution automatically. Demo activation requires explicit operator approval. Live-capital operation requires a future standalone design and review.

## 12. Delivery Phases

### Phase 0: Lock and baseline

- Force live trading off at the application boundary.
- Add characterization tests for current decision, risk, MT5, and Binance behavior.
- Correct stop-price translation, minimum-volume handling, ignored risk caps, and stale shared-position state.
- Establish one reproducible test command.

### Phase 1: Trusted foundation

- Add typed domain models and strict validation.
- Add SQLite migrations and repositories.
- Implement deterministic position sizing and versioned risk policy.
- Store audit and safety events.

### Phase 2: XAU/USD swing vertical slice

- Use closed MT5 4-hour bars with daily context.
- Process signal, order, fill, position, stop/target/expiry, and closure end to end.
- Produce daily equity and performance exports.

### Phase 3: Evaluation system

- Add net performance and risk metrics.
- Add deterministic baselines.
- Add chronological walk-forward evaluation.
- Generate automated promotion reports.

### Phase 4: Cohort expansion

- Add BTC/USD, then EUR/USD, GBP/USD, and USD/JPY.
- Add intraday programs as separate strategy versions.
- Enforce portfolio and correlated-USD risk.

### Phase 5: Paper operations

- Add scheduling, retry safety, reconciliation, health checks, alerts, and backups.
- Run the evidence window and track all promotion criteria.

### Phase 6: Demo promotion

- Produce a signed-off promotion report for each candidate.
- Enable only the approved candidate on MT5 demo or Binance testnet.
- Continue paper-vs-demo reconciliation and automatically disable the candidate on a critical safety event.

## 13. Tracker Design

Repository documentation is canonical for scope and acceptance criteria. Notion mirrors delivery state for day-to-day project management. Work items use stable IDs such as `TA-001` in documentation, Notion, branches, and commits.

Tracker fields:

- ID
- work item
- phase
- status
- priority
- instrument
- horizon
- acceptance criteria
- dependencies
- evidence link
- safety-critical flag
- owner
- target date

Workflow states are `Backlog`, `Ready`, `In Progress`, `Review`, `Verified`, and `Blocked`. `Verified` requires linked acceptance evidence. A summary view shows phase gates, safety-critical work, current blockers, and promotion-metric progress.

## 14. Error Handling and Operations

- Network and venue failures are retried only when an idempotency key makes repetition safe.
- Invalid market data, model output, or broker metadata fails closed and records a safety event.
- LLM unavailability does not fall back to a directional heuristic; it produces no-trade unless the active strategy is explicitly deterministic.
- Database migration or integrity failure prevents the scheduler from trading.
- Reconciliation compares materialized positions with lifecycle events and, in demo mode, the venue account.
- Logs and reports never contain secrets.
- SQLite is backed up before migrations and on a defined operating schedule.

## 15. Testing Strategy

- Unit tests cover decision validation, sizing, stop/target direction, spread and slippage, currency conversion, exposure aggregation, and promotion calculations.
- Property-style tests cover risk invariants: accepted loss never exceeds its configured budget, rounding never increases risk beyond tolerance, and retries never duplicate an order.
- Repository tests cover migrations and transactional lifecycle transitions.
- Adapter contract tests use recorded MT5 and Binance payloads with no network dependency.
- End-to-end tests replay fixed candle sequences through signal, fill, stop/target, close, metrics, and report generation.
- Time and IDs are injectable so tests are deterministic.
- Live network smoke tests remain opt-in and cannot submit orders.

## 16. Documentation Deliverables

- `docs/PROJECT_DIRECTION.md`: mission, principles, scope, and promotion policy
- `docs/ROADMAP.md`: phases, gates, and sequencing
- `docs/TRACKER.md`: work items and current delivery state
- `docs/superpowers/specs/2026-09-02-paper-first-trading-platform-design.md`: this approved design
- `docs/superpowers/plans/2026-09-02-paper-first-trading-platform.md`: implementation tasks after design review

The root README and `docs/TRADING_DESK.md` will link to these documents and clearly distinguish the current implementation from the target architecture.

## 17. Acceptance of This Design

This design is accepted when the repository documentation and Notion tracker consistently describe:

- paper-first operation
- the five-instrument initial cohort
- independent intraday and swing programs
- deterministic risk and sizing
- an immutable lifecycle ledger
- evidence-first promotion thresholds
- explicit exclusion of live-capital execution
