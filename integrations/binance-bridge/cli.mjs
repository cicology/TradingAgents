#!/usr/bin/env node
/**
 * Thin CLI over Kos-M/binance (USDMClient).
 * Public: ping, klines. Private order only with --live AND DESK_ALLOW_LIVE_ORDERS=1.
 */
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));

function loadClientClass() {
  const candidates = [
    "binance",
    path.join(here, "..", "binance", "lib", "index.js"),
  ];
  let lastErr;
  for (const spec of candidates) {
    try {
      const mod = require(spec);
      if (mod.USDMClient) return mod.USDMClient;
    } catch (err) {
      lastErr = err;
    }
  }
  throw new Error(
    `Cannot load Kos-M/binance USDMClient. Run: cd integrations/binance && npm install && npm run build. Last error: ${lastErr}`,
  );
}

function client(needAuth) {
  const USDMClient = loadClientClass();
  const testnet = String(process.env.BINANCE_TESTNET || "").toLowerCase() === "true";
  const opts = {
    beautifyResponses: true,
    disableTimeSync: true,
  };
  if (testnet) opts.baseUrlKey = "usdmtest";
  const key = process.env.BINANCE_API_KEY || "";
  const secret = process.env.BINANCE_API_SECRET || "";
  if (needAuth) {
    if (!key || !secret) {
      fail("BINANCE_API_KEY and BINANCE_API_SECRET are required for this command.");
    }
    opts.api_key = key;
    opts.api_secret = secret;
  }
  return new USDMClient(opts);
}

function fail(message) {
  process.stderr.write(String(message) + "\n");
  process.exit(1);
}

function ok(payload) {
  process.stdout.write(JSON.stringify(payload, null, 2) + "\n");
}

async function main() {
  const [cmd, ...rest] = process.argv.slice(2);
  if (!cmd || cmd === "help") {
    ok({
      commands: ["ping", "klines <SYMBOL> [interval] [limit]", "order <SYMBOL> <BUY|SELL> <qty> [--live]"],
      sdk: "https://github.com/Kos-M/binance",
    });
    return;
  }
  if (cmd === "ping") {
    const usdm = client(false);
    await usdm.testConnectivity();
    ok({ ok: true, venue: "binance-usdm", testnet: String(process.env.BINANCE_TESTNET || "") === "true" });
    return;
  }
  if (cmd === "klines") {
    const symbol = rest[0];
    if (!symbol) fail("Usage: klines <SYMBOL> [interval] [limit]");
    const interval = rest[1] || "1d";
    const limit = Number(rest[2] || 30);
    const usdm = client(false);
    const rows = await usdm.getKlines({ symbol, interval, limit });
    ok({ symbol, interval, count: rows.length, klines: rows });
    return;
  }
  if (cmd === "order") {
    const symbol = rest[0];
    const side = (rest[1] || "").toUpperCase();
    const quantity = Number(rest[2]);
    const live = rest.includes("--live");
    if (!symbol || !["BUY", "SELL"].includes(side) || !quantity) {
      fail("Usage: order <SYMBOL> <BUY|SELL> <qty> [--live]");
    }
    const intended = {
      venue: "binance-usdm",
      symbol,
      side,
      type: "MARKET",
      quantity,
      paper: !live,
    };
    if (!live) {
      ok({ ...intended, status: "paper-logged" });
      return;
    }
    if (String(process.env.DESK_ALLOW_LIVE_ORDERS || "") !== "1") {
      fail("Refusing live order: set DESK_ALLOW_LIVE_ORDERS=1 (and prefer BINANCE_TESTNET=true).");
    }
    const usdm = client(true);
    const result = await usdm.submitNewOrder({
      symbol,
      side,
      type: "MARKET",
      quantity,
    });
    ok({ ...intended, status: "submitted", result });
    return;
  }
  fail(`Unknown command '${cmd}'`);
}

main().catch((err) => fail(err?.stack || err?.message || err));
