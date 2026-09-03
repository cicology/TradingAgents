from __future__ import annotations

import os
from pathlib import Path

import certifi
from dotenv import load_dotenv

os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
os.environ.setdefault("CURL_CA_BUNDLE", certifi.where())

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = PACKAGE_ROOT / "reports"

load_dotenv(PACKAGE_ROOT / ".env")
load_dotenv()

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

DEFAULT_MODEL = os.getenv("OPENROUTER_MODEL", "openrouter/free").strip() or "openrouter/free"
SITE_URL = os.getenv("DESK_SITE_URL", "https://localhost").strip() or "https://localhost"
SITE_NAME = os.getenv("DESK_SITE_NAME", "Oryares Desk").strip() or "Oryares Desk"

# Half-Kelly (0.5) with a 5% hard cap. Full Kelly is not used.
KELLY_FRACTION = float(os.getenv("KELLY_FRACTION", "0.5") or 0.5)
KELLY_CAP = float(os.getenv("KELLY_CAP", "0.05") or 0.05)

# Deterministic stop-risk sizing (trading_desk.sizing, TA-104): the base
# percent of equity risked per trade, independent of LLM confidence. This
# is a config value, never something an LLM proposal supplies — see
# Architectural Rule 2: LLM output must never directly determine
# executable size.
RISK_PCT_PER_TRADE = float(os.getenv("RISK_PCT_PER_TRADE", "1.0") or 1.0)

MODEL_FALLBACKS = [
    DEFAULT_MODEL,
    "openrouter/free",
    "openai/gpt-oss-20b:free",
    "nvidia/nemotron-nano-9b-v2:free",
]


def api_key() -> str:
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is missing. Copy trading_desk/.env.example to "
            "trading_desk/.env and add a key that has not been pasted into chat."
        )
    return key


def unique_models() -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for model in MODEL_FALLBACKS:
        if model and model not in seen:
            seen.add(model)
            ordered.append(model)
    return ordered
