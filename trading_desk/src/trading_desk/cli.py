from __future__ import annotations

import argparse
import json
import sys

from trading_desk import config as _config  # noqa: F401 — load .env and SSL bundle first
from trading_desk.binance_bridge import klines as binance_klines
from trading_desk.binance_bridge import paper_order
from trading_desk.binance_bridge import ping as binance_ping
from trading_desk.brue_runner import analyze_with_brue, list_scripts
from trading_desk.instruments import UNIVERSE, resolve
from trading_desk.kelly import size_position
from trading_desk.mt5_broker import ping as mt5_ping
from trading_desk.mt5_broker import place_order as mt5_place
from trading_desk.mt5_broker import positions as mt5_positions
from trading_desk.mt5_broker import quote as mt5_quote
from trading_desk.pipeline import run_analysis
from trading_desk.reports import write_run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="trading_desk",
        description="Analyse gold, indices, and crypto; Brue strategies; Binance SDK bridge.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("universe", help="List supported instruments")

    analyze = sub.add_parser("analyze", help="Run AI analysis for one or more instruments")
    analyze.add_argument("names", nargs="*", help="Instrument names, e.g. gold btc us500")
    analyze.add_argument("--all", action="store_true", help="Run the full universe")
    analyze.add_argument("--mode", choices=("quick", "full"), default="quick")
    analyze.add_argument("--dry-run", action="store_true", help="Skip OpenRouter; rule-based stub only")
    analyze.add_argument("--json", action="store_true", help="Print JSON to stdout")
    analyze.add_argument("--brue", help="Also run a Brue script (ema_crossover or rsi_extremes)")
    analyze.add_argument("--mt5", action="store_true", help="Route the decision to MT5 (paper unless --mt5-live)")
    analyze.add_argument("--mt5-live", action="store_true", help="Submit a live MT5 deal; requires DESK_ALLOW_LIVE_ORDERS=1")

    brue = sub.add_parser("brue", help="List or run Brue example strategies")
    brue_sub = brue.add_subparsers(dest="brue_cmd", required=True)
    brue_sub.add_parser("list", help="Show shipped .brue scripts")
    brue_run = brue_sub.add_parser("run", help="Run a Brue script on desk market data")
    brue_run.add_argument("script", help="ema_crossover or rsi_extremes")
    brue_run.add_argument("instrument", help="Desk name, e.g. gold")
    brue_run.add_argument("--paper-order", action="store_true", help="Log a paper Binance order from the last signal")

    mt5p = sub.add_parser("mt5", help="MetaTrader 5 account, quotes, and orders")
    mt5_sub = mt5p.add_subparsers(dest="mt5_cmd", required=True)
    mt5_sub.add_parser("ping", help="Connect to a running MT5 terminal")
    mt5_sub.add_parser("positions", help="Open positions")
    mt5_quote = mt5_sub.add_parser("quote", help="Live bid/ask for a desk instrument")
    mt5_quote.add_argument("instrument")
    mt5_order = mt5_sub.add_parser("order", help="Paper-check (default) or live deal from a manual side")
    mt5_order.add_argument("instrument")
    mt5_order.add_argument("side", choices=("BUY", "SELL", "buy", "sell"))
    mt5_order.add_argument("--size-pct", type=float, default=1.0, help="Percent of equity to risk (Kelly cap still applies in analyze)")
    mt5_order.add_argument("--live", action="store_true")

    bnc = sub.add_parser("binance", help="Kos-M/binance SDK commands")
    bnc_sub = bnc.add_subparsers(dest="binance_cmd", required=True)
    bnc_sub.add_parser("ping", help="USDM connectivity")
    bnc_klines = bnc_sub.add_parser("klines", help="Fetch klines via the Node SDK")
    bnc_klines.add_argument("instrument", help="Desk name or raw perp, e.g. gold or BTCUSDT")
    bnc_klines.add_argument("--interval", default="1d")
    bnc_klines.add_argument("--limit", type=int, default=5)
    bnc_order = bnc_sub.add_parser("order", help="Paper (default) or live market order")
    bnc_order.add_argument("instrument")
    bnc_order.add_argument("side", choices=("BUY", "SELL", "buy", "sell"))
    bnc_order.add_argument("quantity", type=float)
    bnc_order.add_argument("--live", action="store_true", help="Submit for real; requires DESK_ALLOW_LIVE_ORDERS=1")

    risk_cmd = sub.add_parser("risk", help="Shared risk state: open positions, daily PnL halt")
    risk_sub = risk_cmd.add_subparsers(dest="risk_cmd", required=True)
    risk_sub.add_parser("status", help="Show open positions and today's realized PnL vs the daily halt")
    risk_sub.add_parser("reset-daily", help="Clear today's realized PnL (does not touch open positions)")
    risk_close = risk_sub.add_parser(
        "close", help="Explicitly close a tracked position and record its realized PnL"
    )
    risk_close.add_argument("venue", help="e.g. mt5, binance")
    risk_close.add_argument("symbol", help="Venue-native symbol, e.g. XAUUSD, BTCUSDT")
    risk_close.add_argument(
        "--realized-pnl-pct", type=float, required=True, help="Realized PnL as a percent of capital"
    )

    kelly_cmd = sub.add_parser("kelly", help="Compute Kelly / half-Kelly / capped size")
    kelly_cmd.add_argument("--win-rate", type=float, default=0.55, help="True-ish win probability 0-1")
    kelly_cmd.add_argument("--rr", type=float, default=2.0, help="Average win / average loss")
    kelly_cmd.add_argument("--fraction", type=float, default=0.5, help="1.0 full, 0.5 half, 0.25 quarter")
    kelly_cmd.add_argument("--cap", type=float, default=0.05, help="Hard cap as fraction of capital")

    args = parser.parse_args(argv)

    if args.command == "universe":
        for item in UNIVERSE.values():
            print(f"{item.name:8} {item.symbol:12} {item.asset_class:8} {item.description}")
        return 0

    if args.command == "brue":
        return _cmd_brue(args)
    if args.command == "mt5":
        return _cmd_mt5(args)
    if args.command == "binance":
        return _cmd_binance(args)
    if args.command == "kelly":
        return _cmd_kelly(args)
    if args.command == "risk":
        return _cmd_risk(args)
    return _cmd_analyze(args)


def _cmd_risk(args: argparse.Namespace) -> int:
    from trading_desk.risk import (
        MAX_DAILY_LOSS_PCT,
        MAX_POSITION_PCT,
        daily_loss_breached,
        open_positions,
        record_close,
        reset_daily,
    )

    if args.risk_cmd == "reset-daily":
        reset_daily()
        print("Daily realized PnL reset to 0.0%. Open positions untouched.")
        return 0

    if args.risk_cmd == "close":
        before = open_positions()
        key = f"{args.venue}:{args.symbol}".upper()
        if key not in before:
            print(f"No tracked open position for {key}.", file=sys.stderr)
            return 1
        record_close(args.venue, args.symbol, realized_pnl_pct=args.realized_pnl_pct)
        print(f"Closed {key}. Recorded realized PnL: {args.realized_pnl_pct:+.2f}%")
        return 0

    breached, pnl_pct = daily_loss_breached()
    print(f"Daily loss halt: {'BREACHED — new orders blocked' if breached else 'clear'} "
          f"({pnl_pct:.2f}% vs -{MAX_DAILY_LOSS_PCT}% limit)")
    print(f"Max position size: {MAX_POSITION_PCT}% of capital per order")
    positions = open_positions()
    if not positions:
        print("Open positions: none")
    else:
        print("Open positions:")
        for key, info in positions.items():
            print(f"  {key:20} {info.get('side'):5} opened {info.get('opened_at')}")
    return 0


def _cmd_analyze(args: argparse.Namespace) -> int:
    names = list(UNIVERSE) if args.all else args.names
    if not names:
        print("Pass instrument names or --all. Try: python -m trading_desk universe", file=sys.stderr)
        return 2

    instruments = resolve(names)
    failures = 0
    for instrument in instruments:
        print(f"Analysing {instrument.name} ({instrument.symbol}) ...", flush=True)
        try:
            result = run_analysis(instrument, mode=args.mode, dry_run=args.dry_run)
            if args.brue:
                result["brue"] = analyze_with_brue(instrument, args.brue)
            if args.mt5 or args.mt5_live:
                result["mt5"] = mt5_place(instrument, result.get("decision") or {}, live=bool(args.mt5_live))
            json_path, md_path = write_run(result)
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAILED {instrument.name}: {exc}", file=sys.stderr)
            continue
        decision = result.get("decision") or {}
        print(
            f"  {decision.get('action')} | {decision.get('verdict')} | "
            f"conf={decision.get('confidence')} size={decision.get('size_pct')}"
        )
        if result.get("brue"):
            print(f"  brue {result['brue'].get('script')}: {result['brue'].get('last_signal')}")
        if result.get("mt5"):
            print(f"  mt5 {result['mt5'].get('status')}: {result['mt5'].get('mt5_symbol')} vol={result['mt5'].get('volume')}")
        print(f"  report: {md_path}")
        if args.json:
            print(json.dumps(result["decision"], indent=2, default=str))
        print(f"  json:   {json_path}")
    return 1 if failures else 0


def _cmd_brue(args: argparse.Namespace) -> int:
    if args.brue_cmd == "list":
        for row in list_scripts():
            flag = "ok" if row["present"] else "MISSING"
            print(f"{row['name']:22} {flag:8} {row['runner']:12} {row['path']}")
        return 0
    instrument = resolve([args.instrument])[0]
    result = analyze_with_brue(instrument, args.script)
    print(json.dumps(result, indent=2, default=str))
    if args.paper_order and result.get("last_signal") in {"BUY", "SELL"}:
        if not instrument.binance_perp:
            print("No Binance perp mapped for this instrument; skip order.", file=sys.stderr)
            return 0
        order = paper_order(instrument.binance_perp, result["last_signal"], 0.001, live=False)
        print("paper order:", json.dumps(order, indent=2))
    return 0


def _perp(name: str) -> str:
    if name.upper().endswith("USDT") or name.upper().endswith("USD"):
        return name.upper()
    inst = resolve([name])[0]
    if not inst.binance_perp:
        raise SystemExit(f"{name} has no Binance perp mapping")
    return inst.binance_perp


def _cmd_binance(args: argparse.Namespace) -> int:
    try:
        if args.binance_cmd == "ping":
            print(json.dumps(binance_ping(), indent=2))
            return 0
        if args.binance_cmd == "klines":
            symbol = _perp(args.instrument)
            print(json.dumps(binance_klines(symbol, args.interval, args.limit), indent=2, default=str))
            return 0
        symbol = _perp(args.instrument)
        payload = paper_order(symbol, args.side, args.quantity, live=args.live)
        print(json.dumps(payload, indent=2, default=str))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        return 1


def _cmd_mt5(args: argparse.Namespace) -> int:
    try:
        if args.mt5_cmd == "ping":
            print(json.dumps(mt5_ping(), indent=2, default=str))
            return 0
        if args.mt5_cmd == "positions":
            print(json.dumps(mt5_positions(), indent=2, default=str))
            return 0
        if args.mt5_cmd == "quote":
            inst = resolve([args.instrument])[0]
            print(json.dumps(mt5_quote(inst), indent=2, default=str))
            return 0
        inst = resolve([args.instrument])[0]
        decision = {
            "action": args.side.upper(),
            "verdict": "APPROVE",
            "size_pct": args.size_pct,
            "confidence": 50,
        }
        print(json.dumps(mt5_place(inst, decision, live=args.live), indent=2, default=str))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        return 1


def _cmd_kelly(args: argparse.Namespace) -> int:
    result = size_position(args.win_rate, args.rr, fraction_of_full=args.fraction, cap=args.cap)
    print(json.dumps(
        {
            "win_rate": args.win_rate,
            "reward_risk": args.rr,
            "full_kelly": round(result.full, 4),
            "full_kelly_pct": f"{result.full:.1%}",
            "fractional": round(result.fractional, 4),
            "fractional_pct": f"{result.fractional:.1%}",
            "capped": round(result.capped, 4),
            "capped_pct": f"{result.capped:.1%}",
            "cap": args.cap,
            "edge": result.edge,
            "note": "Desk uses half-Kelly + 5% cap. Full Kelly assumes you know p and b; you do not.",
        },
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
