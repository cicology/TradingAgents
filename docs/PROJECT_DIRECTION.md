# Oryares Project Direction

Last updated: 2026-09-02

## Mission

Build a trustworthy, paper-first trading research desk for XAU/USD, BTC/USD, EUR/USD, GBP/USD, and USD/JPY. The desk must prove that a versioned strategy has positive expectancy after realistic trading costs before it can be considered for demo execution.

The current codebase is an analysis prototype. The approved direction is an evidence and execution-lifecycle platform: reproducible market snapshots, validated decisions, deterministic risk, simulated fills, complete position outcomes, and objective promotion gates.

## What We Are Building

Two independent trading programs share infrastructure but never share performance claims:

| Program | Signal timeframe | Context timeframe | Intended holding period |
|---|---|---|---|
| Intraday | Closed 15-minute bars | Closed 1-hour bars | Minutes to one trading day |
| Swing | Closed 4-hour bars | Closed daily bars | Roughly 1–10 days |

Initial instruments:

- XAU/USD
- BTC/USD
- EUR/USD
- GBP/USD
- USD/JPY

Gold and FX use MT5 market data because MT5 is the intended demo venue. BTC uses Binance market data. Polybot remains a separate Polymarket research and execution system.

## Authority Boundaries

AI agents may interpret technical, macro, regime, and approved news evidence. They may recommend `BUY`, `SELL`, or `HOLD` and explain the thesis.

AI agents may not:

- calculate or override position size
- supply an assumed win probability for Kelly sizing
- bypass stale-data, spread, loss, or exposure controls
- reset a risk halt
- promote a strategy to demo or live execution

Deterministic code validates decisions, calculates risk, simulates execution, reconciles positions, and evaluates promotion criteria.

## Operating Policy

Live-capital execution is outside the approved roadmap and stays disabled. Paper trading is the default and required mode. Demo execution is a later, explicit promotion decision—not a command-line shortcut.

Initial risk policy:

- 0.5% risk per trade
- 1.0% maximum combined risk per instrument
- 2.0% maximum open portfolio risk
- 1.5% maximum correlated USD-bucket risk
- 2.0% realized daily-loss halt
- 5.0% rolling seven-day loss halt
- 10.0% peak-to-trough drawdown pause

Orders with missing or invalid stops, stale prices, excessive spread, uncalculable risk, or broker minimum volume above the risk budget are rejected.

## Definition of Success

A candidate is eligible for a paper-to-demo review only when, for one instrument, strategy version, and horizon, it has:

- at least 100 closed paper trades
- at least 90 elapsed calendar days
- positive expectancy after spread, slippage, and commissions
- profit factor of at least 1.20
- maximum drawdown no greater than 10%
- better risk-adjusted performance than its declared non-AI baseline
- zero unresolved critical safety violations
- reproducible results on an untouched chronological evaluation window

Passing these gates creates a review report. It never enables execution automatically.

## Near-Term Priority

The first delivery slice is XAU/USD swing trading end to end. Before that slice begins, Phase 0 locks live execution, creates a regression-test foundation, and fixes known safety defects in stop handling, minimum-volume rounding, risk caps, and position reconciliation.

See [ROADMAP.md](ROADMAP.md), [TRACKER.md](TRACKER.md), and the [approved design](superpowers/specs/2026-09-02-paper-first-trading-platform-design.md).
