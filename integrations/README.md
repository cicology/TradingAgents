# Integrations

Vendored strategy language and Binance connector used by Oryares Desk.

| Path | Upstream | Role |
|---|---|---|
| [`brue/`](brue/) | [cicology/brue](https://github.com/cicology/brue) | Chart/backtest language (examples + `SYNTAX.md`) |
| [`binance/`](binance/) | [Kos-M/binance](https://github.com/Kos-M/binance) | Node SDK for Binance REST + WebSockets |
| [`binance-bridge/`](binance-bridge/) | this repo | Small CLI the Python desk calls |

## One-time setup

**From the repo root** (`TradingAgents`, not `binance-bridge`):

```powershell
.\setup-integrations.ps1
```

Or, if you are already inside `integrations\binance-bridge`:

```powershell
npm run setup
```

`npm run setup` builds the sibling `../binance` SDK, then installs this bridge. Do not run `cd integrations/binance` from inside `binance-bridge` — that path does not exist.

Public ping (from repo root, after setup):

```powershell
node integrations/binance-bridge/cli.mjs ping
python -m trading_desk binance ping
```

Live market orders stay off unless `DESK_ALLOW_LIVE_ORDERS=1`. Prefer `BINANCE_TESTNET=true`.
