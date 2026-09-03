# Phase 0 Operator and Verification Runbook

Last updated: 2026-09-03

This runbook covers the desk as it exists at the end of Phase 0 (TA-001
through TA-008). It is an operator document, not a product promise: the
desk is a **paper-only research prototype**. Nothing here authorizes or
enables live-capital execution.

## 1. Local setup

```powershell
cd trading_desk
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e ".[test]"
copy .env.example .env
```

Edit `trading_desk\.env` and set `OPENROUTER_API_KEY` to a **new** key that
has never been pasted into a chat session. All other variables have safe
defaults (see below) and are optional.

If you already have the desk's runtime dependencies (`pandas`, `httpx`,
`python-dotenv`, `certifi`, and — on Windows — `MetaTrader5`) installed
globally or in another environment, `python -m pip install -e ".[test]"`
only needs to add `pytest`; the desk does not require a dedicated venv, it
is just the recommended isolation.

## 2. Required environment variables

None of these are secrets except `OPENROUTER_API_KEY` and, if you use the
Binance bridge with authenticated calls, `BINANCE_API_KEY` /
`BINANCE_API_SECRET`. Never commit `.env` or paste these values into a
report, log, fixture, or issue.

| Variable | Default | Purpose |
|---|---|---|
| `OPENROUTER_API_KEY` | *(required for non-dry-run analysis)* | LLM analyst calls. Omit and use `--dry-run` to run without one. |
| `OPENROUTER_MODEL` | `openrouter/free` | Primary model; the client falls back through `MODEL_FALLBACKS` on failure. |
| `MAX_POSITION_PCT` | `5` | Hard ceiling on position size (% of capital) the shared risk gate enforces on every venue. |
| `MAX_DAILY_LOSS_PCT` | `2` | Daily realized-loss halt (shared risk gate, all venues). |
| `MT5_MAX_DAILY_LOSS_PCT` | `3` | A second, MT5-specific circuit breaker computed from broker deal history. |
| `MT5_TERMINAL_PATH` | *(auto-detect)* | Path to `terminal64.exe` if MT5 isn't found automatically. |
| `MT5_SYMBOL_<NAME>` | see `.env.example` | Override broker symbol mapping per instrument (e.g. `MT5_SYMBOL_GOLD=XAUUSDm`). |
| `MT5_DEVIATION` | `30` | Allowed price deviation in points for MT5 order requests. |
| `BINANCE_API_KEY` / `BINANCE_API_SECRET` | *(unset)* | Only needed for authenticated Binance calls; `ping`/`klines` work without them. |
| `BINANCE_TESTNET` | `true` | Route the Node bridge at the USDM testnet base URL. |
| `KELLY_FRACTION` / `KELLY_CAP` | `0.5` / `0.05` | Fractional-Kelly and hard-cap inputs to `pipeline._normalize_decision`. |
| `DESK_ALLOW_LIVE_ORDERS` | `0` | **Ignored during Phase 0.** See §3 — this variable cannot enable live execution regardless of value. |

## 3. Paper-only guarantee

`trading_desk.operating_mode.require_paper_mode()` is the single
authoritative gate. It raises `PaperOnlyError` whenever a caller asks for
`live_requested=True` — **unconditionally**, ignoring `DESK_ALLOW_LIVE_ORDERS`
and any other environment variable. It is called as the first statement in:

- `mt5_broker.place_order()` — before `connect()` is ever called.
- `binance_bridge.paper_order()` — before the Node bridge subprocess is invoked.

The Node bridge (`integrations/binance-bridge/cli.mjs`) carries a second,
independent hard block on `--live` so a direct invocation of the bridge
(bypassing the Python CLI entirely) also cannot submit a live order.

This means: no CLI flag (`--live`, `--mt5-live`), no environment variable,
and no direct bridge invocation can place a real order in this build. The
only way live execution becomes possible is a future promotion decision
that replaces `operating_mode.py` — see `docs/TRACKER.md` Gate E7.

### How to verify no real-order path is enabled

Run every known bypass attempt and confirm each fails with a paper-only
message and no adapter side effect:

```powershell
$env:PYTHONPATH = "trading_desk/src"
python -m trading_desk mt5 order gold BUY --live
python -m trading_desk analyze gold --dry-run --mt5-live
python -m trading_desk binance order btc BUY --equity 10000 --entry 50000 --stop 49000 --live
$env:DESK_ALLOW_LIVE_ORDERS = "1"
python -m trading_desk binance order btc BUY --equity 10000 --entry 50000 --stop 49000 --live
Remove-Item Env:\DESK_ALLOW_LIVE_ORDERS
node integrations/binance-bridge/cli.mjs order BTCUSDT BUY 0.001 --live
```

Expected: every command prints a "Phase 0 is paper-only" message to
stderr and exits non-zero. None should attempt a real MT5 terminal
connection or Binance authenticated call — you can confirm this by running
without MT5 open / without `BINANCE_API_KEY` set and observing that the
failure happens immediately, not after a connection attempt.

The regression suite pins this behavior automatically —
`trading_desk/tests/test_operating_mode.py`,
`test_paper_lock_adapters.py`, and `test_cli_paper_lock.py` assert the
same bypass attempts fail before any adapter side effect runs.

## 4. Test commands

```powershell
$env:PYTHONPATH = "trading_desk/src"
python -m compileall -q trading_desk/src
python -m pytest trading_desk/tests -q
python -m trading_desk universe
```

Or, with the package installed (`pip install -e ".[test]"`, from
`trading_desk/`):

```powershell
python -m compileall -q src
python -m pytest tests -q
python -m trading_desk universe
```

All tests are offline and deterministic: no network, broker, or LLM call
happens during the suite. Every adapter boundary (MT5 `connect()`, the
Binance bridge's `invoke()`) is mocked or monkeypatched in tests that
exercise it.

## 5. CI behavior

`.github/workflows/ci.yml` runs on every push and pull request, on
`ubuntu-latest`:

1. `pip install -e ".[test]"` from `trading_desk/`.
2. `python -m compileall -q src`.
3. `python -m pytest tests -q`.
4. `python -m trading_desk universe` (smoke check).

The `MetaTrader5` dependency is Windows-only (`platform_system ==
'Windows'` marker in `pyproject.toml`), so it is not installed on the
Linux CI runner. This is safe because no offline test calls
`mt5_broker.connect()` directly — every test that exercises MT5 logic
monkeypatches `connect`/`shutdown` or calls pure functions
(`_stop_distance`, `_normalize_volume`) that take plain data, not a live
MT5 session.

## 6. Market-data limitations

- Yahoo Finance (`GC=F`, `^GSPC`, etc.) is a research fallback; it can fail
  TLS handshakes on some Windows configurations and is not a broker feed.
- Binance USD-M/TradFi perp klines are the primary research feed but are
  **not** your eventual MT5/IB CFD quotes — spread, session hours, and
  contract specs differ.
- `dxy` / `vix` cross-asset context is silently skipped if its feed fails;
  check `market.cross_asset` in a report to see what was actually available
  for a given run.
- There is no data-freshness or staleness gate yet (Phase 1, TA-103).
  Treat every `--dry-run` and analysis report as informational only.

## 7. Recovery procedures

**Risk state file corruption or unexpected halt.** Risk state lives at
`trading_desk/reports/risk_state.json` and is written via a temp-file +
atomic replace (`risk._save_state`), so a crash mid-write cannot leave a
truncated file. If the file is ever missing or unreadable, `risk._load_state`
falls back to an empty state (`{"open_positions": {}, "daily": {}}`) rather
than raising — treat that as "state was reset", reconcile open positions
manually against your broker/exchange before trading again, and re-record
them with `desk risk close <venue> <symbol> --realized-pnl-pct <n>` if they
are actually closed, or restart tracking is not currently automatic for
positions that were open before the reset (Phase 1 replaces this JSON file
with a durable, restart-safe ledger — TA-102).

**Stuck duplicate-position block.** `desk risk status` shows all tracked
open positions. If a position is actually closed at the broker but still
tracked, close it explicitly:

```powershell
python -m trading_desk risk close mt5 XAUUSD --realized-pnl-pct -0.4
```

**Daily loss halt won't clear.** It resets automatically at UTC day
rollover. To lift it early (e.g. you've reconciled a false-positive), run
`python -m trading_desk risk reset-daily` — this does not touch open
positions.

## 8. Incident response

1. **Stop new activity.** There is no running daemon in Phase 0 — the desk
   is invoked per-command — so "stopping" means: do not run further
   `analyze --mt5`/`--mt5-live`/`binance order` commands, and revoke any
   API keys you suspect were exposed.
2. **Check for a live path.** Re-run the bypass checklist in §3. If any
   command reaches an adapter (MT5 terminal connect, Binance authenticated
   call) instead of failing closed with a paper-only message, treat that as
   a P0 safety regression: stop use immediately and file it against
   `docs/TRACKER.md` E0.
3. **Inspect state.** Run `desk risk status` and read
   `trading_desk/reports/risk_state.json` directly to see exactly what the
   desk believes is open and today's realized PnL.
4. **Inspect recent reports.** Every analysis run writes
   `trading_desk/reports/<UTC-date>/<name>.md` and `.json` — this is the
   closest thing Phase 0 has to a lifecycle/audit trail (see §9).
5. **Secrets exposure.** If `OPENROUTER_API_KEY` or Binance keys were
   logged, committed, or pasted anywhere, revoke and rotate them
   immediately; they are not covered by any secret-scanning gate yet
   (tracked as a Phase 5 operations gap).

## 9. How to inspect lifecycle events

Phase 0 does not yet have the durable lifecycle/outcome ledger required by
Gate E1 (TA-105) — that is the largest acknowledged product gap. Until
then, "lifecycle" is reconstructed from two sources:

- **`trading_desk/reports/risk_state.json`** — current open positions
  (with `side`, `size_pct`, `opened_at`) and today's realized PnL. This is
  the authoritative *current* state, not a history.
- **`trading_desk/reports/<UTC-date>/<name>.md` / `.json`** — one file per
  analysis run, containing the full agent output, normalized decision, and
  (if `--mt5`/`--mt5-live` or `--paper-order` was used) the resulting
  paper-order response. This is an append-only history but is not
  queryable and is not linked to position close events.

There is currently no single command that reconstructs "what happened to
position X from open to close." Building that is Phase 1's canonical
lifecycle ledger (TA-105) and Phase 2's outcome export (TA-205).

## 10. Known limitations (Phase 0 scope)

- No durable trade lifecycle/outcome ledger (Phase 1).
- No backtesting/evaluation engine or promotion report (Phase 3).
- No product auth, frontend, multi-tenant isolation, or payments (Phase
  5/6).
- No data-freshness, spread, or portfolio-exposure validation on LLM
  output beyond the size-cap and stop-translation fixes in this phase
  (Phase 1, TA-103).
- Binance sizing (`quantity_from_risk`) does not yet fetch live
  `LOT_SIZE`/`MIN_NOTIONAL` exchange filters — `step`/`min_qty`/
  `min_notional` are optional parameters a caller can supply, but the CLI
  does not currently look them up from the exchange. Do not rely on it to
  reject an order that violates real exchange filters it wasn't told
  about.
- The MT5 adapter is Windows-bound (requires an installed, logged-in
  terminal); Linux CI cannot exercise it beyond compile checks and
  monkeypatched unit tests.
- `risk_state.json` is a single local file, not safe for concurrent
  multi-process use and not backed up (Phase 5, TA-504).

## 11. Rollback procedure

The desk is stateless CLI tooling with no running service to roll back in
Phase 0. To roll back a bad change:

```powershell
git log --oneline -10          # find the last known-good commit
git revert <bad-commit-sha>    # preferred: preserves history
```

Do not use `git reset --hard` on a shared branch. If `risk_state.json` was
corrupted by the bad change, restore it from the most recent good copy if
you have one, or accept the reset-to-empty-state behavior in §7 and
reconcile positions manually against the broker/exchange before resuming.
There is no automated backup/restore yet (Phase 5, TA-504) — this is a
tracked gap, not a guarantee.
