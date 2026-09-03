# Oryares Desk — Product, Architecture, and Roadmap

Last updated: 2026-09-02

> This document describes the current v0.1 prototype. The approved target architecture and delivery sequence are documented in [PROJECT_DIRECTION.md](PROJECT_DIRECTION.md), [ROADMAP.md](ROADMAP.md), and [TRACKER.md](TRACKER.md). Live-capital execution is outside the approved roadmap and must remain disabled.

## 0. Phase 0 safety state

The desk is paper-only. `trading_desk.operating_mode.require_paper_mode()` is
the single authoritative gate: Python (both the MT5 and Binance adapters)
and the direct Node bridge reject every live request before any broker or
network submission. `DESK_ALLOW_LIVE_ORDERS` is ignored during Phase 0 —
no environment variable, CLI flag, or direct bridge invocation can enable
it.

Run the offline gate with:

```powershell
$env:PYTHONPATH = "trading_desk/src"
python -m compileall -q trading_desk/src
python -m pytest trading_desk/tests -q
```

Full operator setup, environment variables, incident response, recovery,
and rollback procedures are in [docs/RUNBOOK.md](RUNBOOK.md).

## 1. Aim

Build a project we can use to **analyse and eventually trade gold, equity indices, and crypto**, with **AI models doing the research**, not the order routing.

Success for v1 is not “the bot prints money”. Success is:

- A repeatable analysis run for each instrument
- A structured decision (action, confidence, stop, size cap)
- A paper ledger of those decisions over time
- Documentation of how every signal was produced

Live execution is a later phase, after paper results exist.

## 2. Can we just plug OpenRouter into Polybot?

**No — not if the goal is gold / indices / crypto.**

Polybot is a **Polymarket** stack: Java microservices, ClickHouse, Kafka, and a complete-set arbitrage strategy on BTC/ETH Up/Down binaries. OpenRouter would only add LLM commentary on that prediction-market book. It would not give you XAUUSD, US500, or spot crypto CFDs.

| Need | Polybot today | Desk we are building |
|---|---|---|
| Gold (XAU) | No | Yes — COMEX gold futures via Yahoo (`GC=F`) |
| Indices (US500, NAS100) | No | Yes — `^GSPC`, `^NDX` |
| Crypto | BTC/ETH **Up/Down binaries** on Polymarket | Spot-style series (`BTC-USD`, `ETH-USD`) |
| LLM analysis | None | OpenRouter, free models first |
| Execution | Polymarket CLOB (paper/live) | Paper ledger now; broker later |
| Language | Java 21 | Python 3.11+ |

Keep Polybot as-is if you still want Polymarket research. Do not stretch it into an FX/CFD/crypto desk.

## 3. Design principles

1. **Analysis and execution are separate.** Agents recommend. A risk layer can reject. Nothing places a live order in v0.1.
2. **Numbers first, language second.** Indicators and prices are computed in Python. The model interprets them; it does not invent RSI.
3. **Free models are a budget, not a SLA.** OpenRouter `:free` endpoints rotate, rate-limit (~50 requests/day on a $0 account, higher after prepaid credits), and can 429. The client retries and falls back.
4. **One run, one audit file.** Every analysis writes JSON + Markdown under `trading_desk/reports/`.
5. **No secrets in git.** `OPENROUTER_API_KEY` lives in `trading_desk/.env` only.

## 4. Instrument universe (v0.1)

Primary research feed is **Binance USD-M / TradFi perps** (works without a Yahoo login and avoids Yahoo TLS failures on some Windows setups). Yahoo is a fallback.

| Name | Research feed | Yahoo fallback | Asset class |
|---|---|---|---|
| `gold` | `XAUUSDT` | `GC=F` | Metal |
| `silver` | `XAGUSDT` | `SI=F` | Metal |
| `us500` | `SPXUSDT` | `^GSPC` | Index |
| `nas100` | `QQQUSDT` (ETF proxy) | `^NDX` | Index |
| `dxy` | Yahoo only | `DX-Y.NYB` | FX context |
| `vix` | Yahoo only | `^VIX` | Vol regime |
| `btc` | `BTCUSDT` | `BTC-USD` | Crypto |
| `eth` | `ETHUSDT` | `ETH-USD` | Crypto |

These are **research prices**, not your future MT5/IB CFD quotes (spread, session, and contract will differ). `dxy` / `vix` context is skipped if Yahoo TLS fails.

## 5. Agent pipeline

Inspired by [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents), adapted for metals/indices/crypto (no equity 10-K “fundamentals”).

```text
Market data (OHLCV + indicators + headlines)
        │
        ▼
 ┌──────────────┐   ┌──────────────┐
 │ Technical    │   │ News / macro │     --mode quick: these two only,
 │ analyst      │   │ analyst      │     then jump to Trader
 └──────┬───────┘   └──────┬───────┘
        └────────┬─────────┘
                 ▼
        Bull vs Bear debate                 --mode full
                 ▼
              Trader  →  BUY / SELL / HOLD + size/stop
                 ▼
           Risk manager  →  APPROVE / REDUCE / REJECT
                 ▼
         Report + paper ledger
```

| Mode | LLM calls per symbol | When to use |
|---|---:|---|
| `quick` (default) | 3 (technical, news, trader+risk combined) | Daily scans on the free tier |
| `full` | 6 (adds bull, bear, separate risk) | Deeper session on one name |

A $0 OpenRouter account is typically **50 requests/day**. `quick` on three symbols ≈ 9 calls. `full` on eight symbols can exhaust the day.

### Model routing

Default model: `openrouter/free` (router picks an available free model).

Fallback list (order matters; skip any that 404):

1. `openrouter/free`
2. `openai/gpt-oss-20b:free`
3. `nvidia/nemotron-nano-9b-v2:free`

Override with `OPENROUTER_MODEL` in `.env`. Paid models (for example `openai/gpt-4o`) work on the same client if you have credits — do not use them as the default until paper process is stable.

Headers sent: `HTTP-Referer` and `X-Title` (OpenRouter ranking, optional).

## 6. What “trading” means in each phase

| Phase | Analysis | Paper | Live orders | Broker |
|---|---|---|---|---|
| **0.1 — now** | Yes | Decision log + Brue paper signals | No (kill-switch) | Kos-M/binance SDK, paper unless `DESK_ALLOW_LIVE_ORDERS=1` |
| **0.2** | Yes | Simulated PnL vs next-bar / N-day | No | None |
| **0.3** | Yes | Yes | Optional, kill-switch | Crypto: exchange API (e.g. CCXT). Gold/indices: MT5 or Interactive Brokers |
| **1.0** | Yes | Continuous | Capped live | Same, with hard daily loss and max-position rules in code |

Gold and index **CFDs** need a broker that offers those products (often MT5). Crypto can go through a spot/perp exchange. Do not assume one API covers all three.

## 7. Runbook

Prerequisites: Python 3.11+, an OpenRouter key that has **not** been pasted into chat.

```bash
cd trading_desk
python -m venv .venv
.venv\Scripts\activate
pip install -e .
copy .env.example .env
```

Edit `.env`:

```env
OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_MODEL=openrouter/free
DESK_SITE_URL=https://localhost
DESK_SITE_NAME=Oryares Desk
BINANCE_TESTNET=true
DESK_ALLOW_LIVE_ORDERS=0
```

Commands:

```bash
python -m trading_desk universe
python -m trading_desk analyze gold --dry-run
python -m trading_desk analyze gold --brue ema_crossover --dry-run
python -m trading_desk brue list
python -m trading_desk brue run ema_crossover gold
python -m trading_desk brue run rsi_extremes btc --paper-order --equity 10000
python -m trading_desk binance ping
python -m trading_desk binance klines gold --limit 5
python -m trading_desk binance order btc BUY --equity 10000 --entry 50000 --stop 49000
```

`binance order` sizes quantity from `--equity`/`--entry`/`--stop`/`--size-pct` through the shared risk pipeline — there is no raw quantity argument, so a manual order cannot bypass the position-size cap.

`--dry-run` fetches data and writes a rule-based stub (no API key). Use it to verify Yahoo access.

Reports land in `trading_desk/reports/<UTC-date>/<name>.md` and `.json`.

## 8. Risk and honesty

- Free models are weaker and less consistent than paid frontier models. Expect mixed JSON, missed levels, and confident-sounding errors.
- Yahoo Finance is unofficial and can throttle or change fields.
- Past indicator patterns do not imply future returns.
- If a key was ever pasted into a chat, **revoke it** at [openrouter.ai/settings/keys](https://openrouter.ai/settings/keys) and create a new one.

## 9. Repo map

```text
TradingAgents/
├── README.md
├── docs/TRADING_DESK.md
├── integrations/
│   ├── brue/                 # git submodule: cicology/brue
│   ├── binance/              # git submodule: Kos-M/binance
│   └── binance-bridge/       # Node CLI the Python desk calls
├── trading_desk/
└── polybot/
```

## 11. Brue + Binance

[Brue](https://github.com/cicology/brue) is the London Strategic Edge chart language. This repo vendors the language spec and examples. The desk runs two of those examples on live OHLCV:

- `ema_crossover` — BUY/SELL on 9/21 EMA crosses
- `rsi_extremes` — BUY below RSI 30, SELL above 70

The EUR/GBP pair scripts stay in the examples folder; they need a FX host we do not have yet.

[Kos-M/binance](https://github.com/Kos-M/binance) is the Node SDK. Python never signs Binance payloads itself — it shells to `integrations/binance-bridge/cli.mjs`. Public `ping` / `klines` need no keys. `order` is paper-logged unless you set `DESK_ALLOW_LIVE_ORDERS=1` (prefer `BINANCE_TESTNET=true`).

Setup: [integrations/README.md](../integrations/README.md). From `integrations/binance-bridge` run `npm run setup` (do not `cd integrations/binance` from there).

## 12. Kelly sizing

Signals without size still blow accounts. The desk sizes BUY/SELL with the [Kelly criterion](https://x.com/tigerfl0w/status/2079223461659148713):

`f* = (p * b - q) / b` where `p` is win rate, `q = 1-p`, `b` is average win / average loss.

Practice rules baked in (Thorp / Lo):

- Default **half-Kelly** (`KELLY_FRACTION=0.5`). REDUCE uses a quarter of full.
- Hard cap **5%** of capital (`KELLY_CAP=0.05`) even if Kelly says 32%.
- Model confidence is **shrunk toward 50%**. An LLM saying 80% is not an 80% win rate.
- HOLD / REJECT size to 0. Negative Kelly (no edge) is REJECT.

```powershell
python -m trading_desk kelly --win-rate 0.55 --rr 2
# full 32.5%, half 16.2%, desk cap 5.0%
```

## 13. MetaTrader 5

Gold and indices live on your MT5 broker, not on Binance. The desk talks to a **running, logged-in** terminal via the official `MetaTrader5` Python package.

```powershell
pip install MetaTrader5
# Terminal open, logged in, symbols in Market Watch
python -m trading_desk mt5 ping
python -m trading_desk mt5 quote gold
python -m trading_desk analyze gold --mt5 --dry-run
```

Live deals are unreachable in this Phase 0 build regardless of Algo Trading, `DESK_ALLOW_LIVE_ORDERS`, or `--mt5-live` — see [§0 Phase 0 safety state](#0-phase-0-safety-state) below. Paper is `order_check` only. Daily loss stop: `MT5_MAX_DAILY_LOSS_PCT=3`. Broker symbol names differ — set `MT5_SYMBOL_GOLD=XAUUSD` (or `GOLD`, `XAUUSDm`) to match Market Watch.

This does not make money by itself. It routes half-Kelly-capped size to your account. Demo first.

## 10. Next implementation slices (after v0.1)

1. Paper PnL: mark decisions against subsequent closes
2. Scheduled scan (Windows Task Scheduler / cron) for the liquid session you care about
3. News vendor with a real API if Yahoo headlines are too thin
4. Broker adapter behind a feature flag, starting with crypto paper on an exchange testnet
5. Dashboard of the paper ledger (optional; reports are enough at first)
