# MetaTrader 5

Python talks to a **local MT5 terminal**. The terminal must be installed, running, and logged into a demo or live account. Enable **Algo Trading** (toolbar button) before any live order.

## Map desk names to your broker symbols

Brokers rename gold/indices. Defaults:

| Desk | Default MT5 |
|---|---|
| gold | XAUUSD |
| silver | XAGUSD |
| us500 | US500 |
| nas100 | NAS100 |
| btc | BTCUSD |
| eth | ETHUSD |

Override in `trading_desk/.env`, for example `MT5_SYMBOL_GOLD=GOLD` or `XAUUSDm`.

## Commands

```powershell
python -m trading_desk mt5 ping
python -m trading_desk mt5 quote gold
python -m trading_desk mt5 positions
python -m trading_desk analyze gold --mt5
python -m trading_desk analyze gold --mt5-live   # also DESK_ALLOW_LIVE_ORDERS=1
```

`--mt5` runs `order_check` (paper). `--mt5-live` calls `order_send`. Dry-run analysis that REJECTS will skip the order.

If initialize fails, set `MT5_TERMINAL_PATH` to `terminal64.exe`.

## Money

No adapter can guarantee profit. Use a **demo** account until the paper ledger and Kelly size look sane. Live starts at the 5% Kelly cap, with a 3% daily loss breaker.
