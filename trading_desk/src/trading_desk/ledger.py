"""Durable SQLite-backed ledger (TA-102) with immutable lifecycle events
(TA-105).

This is the desk's single persistence boundary: a connection factory, a
numbered migration runner, and repository functions. Nothing outside this
module should execute SQL directly — that keeps a future move to
PostgreSQL (Gate E1 target) a change to this file alone, not a
repo-wide rewrite.

`lifecycle_events` is append-only at the database level: UPDATE and DELETE
are rejected by triggers, not merely omitted from this module's API. State
(`current_position`) is always reconstructed by replaying durable events —
never cached in memory — so a restart cannot lose or desync state, and a
duplicate write (same `event_id`) is a no-op, not a duplicate.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from trading_desk.config import REPORTS_DIR
from trading_desk.domain import Action, LifecycleEvent, LifecycleEventType, Outcome, TradeDecision, Verdict

DEFAULT_DB_PATH = REPORTS_DIR / "ledger.sqlite3"

# Each entry is (version, sql). Numbered and applied in order, once each,
# tracked in schema_version. Add new migrations by appending — never edit
# an already-shipped one.
_MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
        CREATE TABLE IF NOT EXISTS lifecycle_events (
            event_id      TEXT PRIMARY KEY,
            venue         TEXT NOT NULL,
            symbol        TEXT NOT NULL,
            event_type    TEXT NOT NULL,
            occurred_at   TEXT NOT NULL,
            payload       TEXT NOT NULL,
            recorded_at   TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_lifecycle_events_venue_symbol
            ON lifecycle_events(venue, symbol, occurred_at);

        CREATE TRIGGER IF NOT EXISTS trg_lifecycle_events_no_update
        BEFORE UPDATE ON lifecycle_events
        BEGIN
            SELECT RAISE(ABORT, 'lifecycle_events is append-only: UPDATE is not permitted');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_lifecycle_events_no_delete
        BEFORE DELETE ON lifecycle_events
        BEGIN
            SELECT RAISE(ABORT, 'lifecycle_events is append-only: DELETE is not permitted');
        END;

        CREATE TABLE IF NOT EXISTS safety_events (
            event_id      TEXT PRIMARY KEY,
            category      TEXT NOT NULL,
            occurred_at   TEXT NOT NULL,
            payload       TEXT NOT NULL,
            recorded_at   TEXT NOT NULL
        );

        CREATE TRIGGER IF NOT EXISTS trg_safety_events_no_update
        BEFORE UPDATE ON safety_events
        BEGIN
            SELECT RAISE(ABORT, 'safety_events is append-only: UPDATE is not permitted');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_safety_events_no_delete
        BEFORE DELETE ON safety_events
        BEGIN
            SELECT RAISE(ABORT, 'safety_events is append-only: DELETE is not permitted');
        END;
        """,
    ),
    (
        2,
        """
        CREATE TABLE IF NOT EXISTS decisions (
            decision_id       TEXT PRIMARY KEY,
            instrument        TEXT NOT NULL,
            strategy_version  TEXT NOT NULL,
            action            TEXT NOT NULL,
            verdict           TEXT NOT NULL,
            size_pct          REAL NOT NULL,
            entry             REAL,
            stop              REAL,
            targets           TEXT NOT NULL,
            rationale         TEXT NOT NULL,
            model             TEXT,
            generated_at      TEXT NOT NULL,
            recorded_at       TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_decisions_instrument_strategy
            ON decisions(instrument, strategy_version, generated_at);

        CREATE TRIGGER IF NOT EXISTS trg_decisions_no_update
        BEFORE UPDATE ON decisions
        BEGIN
            SELECT RAISE(ABORT, 'decisions is append-only: UPDATE is not permitted');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_decisions_no_delete
        BEFORE DELETE ON decisions
        BEGIN
            SELECT RAISE(ABORT, 'decisions is append-only: DELETE is not permitted');
        END;
        """,
    ),
    (
        3,
        """
        CREATE TABLE IF NOT EXISTS outcomes (
            outcome_id        TEXT PRIMARY KEY,
            venue             TEXT NOT NULL,
            symbol            TEXT NOT NULL,
            strategy_version  TEXT NOT NULL,
            opened_at         TEXT NOT NULL,
            closed_at         TEXT NOT NULL,
            realized_pnl_pct  REAL NOT NULL,
            recorded_at       TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_outcomes_strategy_closed
            ON outcomes(strategy_version, closed_at);

        CREATE TRIGGER IF NOT EXISTS trg_outcomes_no_update
        BEFORE UPDATE ON outcomes
        BEGIN
            SELECT RAISE(ABORT, 'outcomes is append-only: UPDATE is not permitted');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_outcomes_no_delete
        BEFORE DELETE ON outcomes
        BEGIN
            SELECT RAISE(ABORT, 'outcomes is append-only: DELETE is not permitted');
        END;
        """,
    ),
]

_OPEN_EVENT_TYPES = {LifecycleEventType.OPEN}
_CLOSE_EVENT_TYPES = {LifecycleEventType.CLOSE, LifecycleEventType.CANCEL, LifecycleEventType.REJECT}


def connect(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn)
    return conn


def schema_version(conn: sqlite3.Connection) -> int:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return row[0] or 0


def migrate(conn: sqlite3.Connection) -> None:
    current = schema_version(conn)
    for version, sql in _MIGRATIONS:
        if version <= current:
            continue
        conn.executescript(sql)
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
        conn.commit()


def record_lifecycle_event(conn: sqlite3.Connection, event: LifecycleEvent) -> bool:
    """Insert a lifecycle event. Returns True if newly recorded, False if
    `event_id` already existed — a duplicate write is a no-op, not an
    error and not a second row."""
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO lifecycle_events
            (event_id, venue, symbol, event_type, occurred_at, payload, recorded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event.event_id,
            event.venue,
            event.symbol,
            event.event_type.value,
            event.occurred_at.isoformat(),
            json.dumps(event.payload, default=str),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    return cursor.rowcount > 0


def list_lifecycle_events(
    conn: sqlite3.Connection, *, venue: str | None = None, symbol: str | None = None
) -> list[LifecycleEvent]:
    query = "SELECT event_id, venue, symbol, event_type, occurred_at, payload FROM lifecycle_events"
    clauses: list[str] = []
    params: list[Any] = []
    if venue is not None:
        clauses.append("venue = ?")
        params.append(venue)
    if symbol is not None:
        clauses.append("symbol = ?")
        params.append(symbol)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY occurred_at ASC, rowid ASC"
    rows = conn.execute(query, params).fetchall()
    return [
        LifecycleEvent(
            event_id=row[0],
            venue=row[1],
            symbol=row[2],
            event_type=LifecycleEventType(row[3]),
            occurred_at=datetime.fromisoformat(row[4]),
            payload=json.loads(row[5]),
        )
        for row in rows
    ]


def current_position(conn: sqlite3.Connection, venue: str, symbol: str) -> dict[str, Any] | None:
    """Reconstruct current open-position state by replaying this
    venue+symbol's lifecycle events in order. Always derived from durable
    events — restart recovery is just calling this again."""
    state: dict[str, Any] | None = None
    for event in list_lifecycle_events(conn, venue=venue, symbol=symbol):
        if event.event_type in _OPEN_EVENT_TYPES:
            state = {
                "side": event.payload.get("side"),
                "size_pct": event.payload.get("size_pct"),
                "opened_at": event.occurred_at.isoformat(),
            }
        elif event.event_type in _CLOSE_EVENT_TYPES:
            state = None
    return state


def record_safety_event(conn: sqlite3.Connection, event_id: str, category: str, payload: dict[str, Any]) -> bool:
    """Append-only audit trail for safety-relevant decisions (paper-only
    rejections, risk gate blocks, order_check failures, etc.) — separate
    from the position lifecycle so it can record events that never
    produced a position at all."""
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO safety_events (event_id, category, occurred_at, payload, recorded_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            event_id,
            category,
            datetime.now(timezone.utc).isoformat(),
            json.dumps(payload, default=str),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    return cursor.rowcount > 0


def list_safety_events(conn: sqlite3.Connection, *, category: str | None = None) -> list[dict[str, Any]]:
    query = "SELECT event_id, category, occurred_at, payload FROM safety_events"
    params: list[Any] = []
    if category is not None:
        query += " WHERE category = ?"
        params.append(category)
    query += " ORDER BY occurred_at ASC, rowid ASC"
    rows = conn.execute(query, params).fetchall()
    return [
        {"event_id": row[0], "category": row[1], "occurred_at": row[2], "payload": json.loads(row[3])}
        for row in rows
    ]


def record_decision(conn: sqlite3.Connection, decision_id: str, decision: TradeDecision) -> bool:
    """Persist a canonical TradeDecision — the E1 exit criterion 'every
    decision is durable and traceable' means the decision itself, not just
    the lifecycle events that may follow it. Idempotent by decision_id:
    a duplicate write is a no-op and does not overwrite the original."""
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO decisions
            (decision_id, instrument, strategy_version, action, verdict, size_pct,
             entry, stop, targets, rationale, model, generated_at, recorded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            decision_id,
            decision.instrument,
            decision.strategy_version,
            decision.action.value,
            decision.verdict.value,
            decision.size_pct,
            decision.entry,
            decision.stop,
            json.dumps(list(decision.targets)),
            decision.rationale,
            decision.model,
            decision.generated_at.isoformat(),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    return cursor.rowcount > 0


def get_decision(conn: sqlite3.Connection, decision_id: str) -> TradeDecision | None:
    row = conn.execute(
        """
        SELECT instrument, strategy_version, action, verdict, size_pct,
               entry, stop, targets, rationale, model, generated_at
        FROM decisions WHERE decision_id = ?
        """,
        (decision_id,),
    ).fetchone()
    if row is None:
        return None
    return TradeDecision(
        instrument=row[0],
        strategy_version=row[1],
        action=Action(row[2]),
        verdict=Verdict(row[3]),
        size_pct=row[4],
        entry=row[5],
        stop=row[6],
        targets=tuple(json.loads(row[7])),
        rationale=row[8],
        model=row[9],
        generated_at=datetime.fromisoformat(row[10]),
    )


def record_outcome(conn: sqlite3.Connection, outcome_id: str, outcome: Outcome) -> bool:
    """Persist a closed-trade Outcome. Idempotent by outcome_id: a
    duplicate write is a no-op and does not overwrite the original."""
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO outcomes
            (outcome_id, venue, symbol, strategy_version, opened_at, closed_at, realized_pnl_pct, recorded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            outcome_id,
            outcome.venue,
            outcome.symbol,
            outcome.strategy_version,
            outcome.opened_at.isoformat(),
            outcome.closed_at.isoformat(),
            outcome.realized_pnl_pct,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    return cursor.rowcount > 0


def list_outcomes(
    conn: sqlite3.Connection, *, strategy_version: str | None = None, symbol: str | None = None
) -> list[Outcome]:
    query = "SELECT venue, symbol, strategy_version, opened_at, closed_at, realized_pnl_pct FROM outcomes"
    clauses: list[str] = []
    params: list[Any] = []
    if strategy_version is not None:
        clauses.append("strategy_version = ?")
        params.append(strategy_version)
    if symbol is not None:
        clauses.append("symbol = ?")
        params.append(symbol)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY closed_at ASC, rowid ASC"
    rows = conn.execute(query, params).fetchall()
    return [
        Outcome(
            venue=row[0],
            symbol=row[1],
            strategy_version=row[2],
            opened_at=datetime.fromisoformat(row[3]),
            closed_at=datetime.fromisoformat(row[4]),
            realized_pnl_pct=row[5],
        )
        for row in rows
    ]
