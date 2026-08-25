# Oryares Desk

Python analysis desk: gold, indices, and crypto, with OpenRouter (free models by default).

Full product notes: [../docs/TRADING_DESK.md](../docs/TRADING_DESK.md)

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .
copy .env.example .env
```

Set `OPENROUTER_API_KEY` in `.env`. Never commit that file.

## Commands

```bash
python -m trading_desk universe
python -m trading_desk analyze gold --dry-run
python -m trading_desk brue list
python -m trading_desk brue run ema_crossover gold
python -m trading_desk binance ping
python -m trading_desk kelly --win-rate 0.55 --rr 2
python -m trading_desk mt5 ping
```

Market data comes from Binance perps first (`XAUUSDT`, `SPXUSDT`, `QQQUSDT`, `BTCUSDT`, `ETHUSDT`). Yahoo is a fallback and may fail on some Windows TLS setups.

## Layout

```text
src/trading_desk/
  cli.py           entrypoint
  config.py        env + model fallbacks
  instruments.py   gold / indices / crypto map
  market.py        Yahoo OHLCV, indicators, news
  llm.py           OpenRouter client
  agents.py        prompts + JSON parse
  pipeline.py      quick / full runs
  reports.py       markdown + JSON + paper log
```
