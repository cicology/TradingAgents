# Oryares TradingAgents

Research workspace for **AI-assisted trading analysis** on gold, equity indices, and crypto.

This folder contains three layers. They do not share a live execution path unless you turn that on.

| Layer | Path | What it is | What it trades |
|---|---|---|---|
| **Desk** | [`trading_desk/`](trading_desk/) | Multi-agent analysis + Brue scripts | Gold, indices, crypto — paper by default |
| **Integrations** | [`integrations/`](integrations/) | [Brue](https://github.com/cicology/brue) language + [Kos-M/binance](https://github.com/Kos-M/binance) SDK | Binance USDM/TradFi perps |
| **Polybot** | [`polybot/`](polybot/) | Java HFT stack for Polymarket | BTC/ETH Up/Down binaries |

**Start here:** [docs/TRADING_DESK.md](docs/TRADING_DESK.md)

## What we are aiming to achieve

A desk that can:

1. Pull market data for gold, major indices, and crypto
2. Run specialist AI agents (technical, news/macro, bull, bear, trader, risk)
3. Produce a documented BUY / SELL / HOLD with size, stop, and invalidation
4. Paper-trade those signals
5. Later connect a real broker — only after paper results are logged and reviewed

AI does **analysis**. Risk rules and you decide whether anything is sent to a broker.

## Quick start (desk)

```bash
cd trading_desk
python -m venv .venv
.venv\Scripts\activate
pip install -e .
copy .env.example .env
```

Put a **new** OpenRouter key in `.env` as `OPENROUTER_API_KEY`. Do not reuse a key that has been pasted into chat.

```bash
python -m trading_desk universe
python -m trading_desk analyze gold --dry-run
python -m trading_desk analyze gold --brue ema_crossover --dry-run
python -m trading_desk brue list
python -m trading_desk brue run ema_crossover gold
python -m trading_desk binance ping
python -m trading_desk kelly --win-rate 0.55 --rr 2
python -m trading_desk mt5 ping
```

Binance SDK setup (once), **from the repo root**:

```powershell
.\setup-integrations.ps1
```

If you are already in `integrations\binance-bridge`, run `npm run setup` there. Live orders stay blocked unless `DESK_ALLOW_LIVE_ORDERS=1`.

## Disclaimer

This software is for research and education. It is not financial advice. Markets can gap, models hallucinate, and free LLM endpoints are rate-limited and unreliable. Do not send live orders until you have a broker integration, risk limits, and a paper-trading track record you accept.
