"""TA-202: versioned evidence hashing.

`compute_evidence_hash` is deterministic: the same bars, instrument, and
horizon always produce the same evidence_id. That is the whole point — a
replayed run can prove it saw the exact same inputs as the original by
comparing hashes, and any drift (even a single changed bar) produces a
different hash rather than silently passing.
"""

from __future__ import annotations

import hashlib
import json

from trading_desk.market_data import Bar


def _canonical_bars(bars: list[Bar]) -> list[list[float]]:
    return [
        [bar.time.timestamp(), bar.open, bar.high, bar.low, bar.close, bar.volume]
        for bar in bars
    ]


def compute_evidence_hash(bars: list[Bar], *, instrument: str, horizon: str) -> str:
    payload = {
        "instrument": instrument,
        "horizon": horizon,
        "bars": _canonical_bars(bars),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
