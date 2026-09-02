"""SQLite store shared by the native kill/restart proof processes.

Two independent OS processes use this file:

* the **relay** (`relay_proc.py`) reads unsent `outbox_events` and flips them
  `sent=1` after publishing (publish-then-mark-sent, matching `OutboxRelay`);
* the **consumer** (`consumer_proc.py`) records applied `event_id`s and a
  derived positions/cash projection.

The consumer's dedupe table is **durable on purpose**: the proof *kills and
restarts the consumer process*, so an in-memory `seen` set (as used by the
Java `cg:phase5-poc` POC bean) could not survive a restart. Persisting
`processed_events` is exactly what the real risk-engine consumer will do, and
it is what makes "applied exactly once across a crash before XACK" provable
here. `apply()` writes the dedupe row and the projection in ONE transaction, so
a crash after apply / before XACK still leaves the effect recorded once.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Dict, List, Optional, Tuple


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init(db_path: str) -> None:
    conn = connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS outbox_events(
                seq         INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id    TEXT UNIQUE NOT NULL,
                event_type  TEXT NOT NULL,
                payload     TEXT NOT NULL,
                sent        INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS processed_events(
                event_id    TEXT PRIMARY KEY
            );
            CREATE TABLE IF NOT EXISTS proj_cash(
                account_id  TEXT PRIMARY KEY,
                cash        REAL NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS proj_positions(
                account_id  TEXT NOT NULL,
                symbol      TEXT NOT NULL,
                qty         REAL NOT NULL DEFAULT 0,
                PRIMARY KEY(account_id, symbol)
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


# --- seeding ------------------------------------------------------------
def seed_outbox(db_path: str, events: List[dict]) -> None:
    """Insert outbox rows in order. Each event: {event_id, event_type, payload}."""
    conn = connect(db_path)
    try:
        for e in events:
            conn.execute(
                "INSERT INTO outbox_events(event_id, event_type, payload, sent) "
                "VALUES(?,?,?,0)",
                (e["event_id"], e["event_type"], e["payload"]),
            )
        conn.commit()
    finally:
        conn.close()


def init_projection(db_path: str, account_id: str, cash: float) -> None:
    conn = connect(db_path)
    try:
        conn.execute(
            "INSERT INTO proj_cash(account_id, cash) VALUES(?,?) "
            "ON CONFLICT(account_id) DO UPDATE SET cash=excluded.cash",
            (account_id, cash),
        )
        conn.commit()
    finally:
        conn.close()


# --- relay side ---------------------------------------------------------
def unsent_outbox(db_path: str) -> List[Tuple[str, str, str]]:
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT event_id, event_type, payload FROM outbox_events "
            "WHERE sent=0 ORDER BY seq"
        ).fetchall()
        return [(r[0], r[1], r[2]) for r in rows]
    finally:
        conn.close()


def unsent_count(db_path: str) -> int:
    conn = connect(db_path)
    try:
        return int(
            conn.execute("SELECT COUNT(*) FROM outbox_events WHERE sent=0").fetchone()[0]
        )
    finally:
        conn.close()


def mark_sent(db_path: str, event_id: str) -> None:
    conn = connect(db_path)
    try:
        conn.execute("UPDATE outbox_events SET sent=1 WHERE event_id=?", (event_id,))
        conn.commit()
    finally:
        conn.close()


# --- consumer side ------------------------------------------------------
def already_processed(db_path: str, event_id: str) -> bool:
    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT 1 FROM processed_events WHERE event_id=?", (event_id,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def apply(db_path: str, event_id: str, account_id: str, symbol: str,
          qty_after: float, cash_delta: float) -> bool:
    """Apply one event's effect with strict dedupe, atomically.

    Returns True if newly applied, False if it was a duplicate (no-op). The
    dedupe insert and the projection update commit together, so a crash after
    this call (but before XACK) still leaves the effect recorded exactly once.
    """
    conn = connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("BEGIN IMMEDIATE")
        # Strict dedupe: PK conflict => already applied.
        try:
            cur.execute(
                "INSERT INTO processed_events(event_id) VALUES(?)", (event_id,)
            )
        except sqlite3.IntegrityError:
            conn.rollback()
            return False
        cur.execute(
            "UPDATE proj_cash SET cash=cash+? WHERE account_id=?",
            (cash_delta, account_id),
        )
        cur.execute(
            "INSERT INTO proj_positions(account_id, symbol, qty) VALUES(?,?,?) "
            "ON CONFLICT(account_id, symbol) DO UPDATE SET qty=excluded.qty",
            (account_id, symbol, qty_after),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def processed_ids(db_path: str) -> List[str]:
    conn = connect(db_path)
    try:
        rows = conn.execute("SELECT event_id FROM processed_events").fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


def projection(db_path: str, account_id: str) -> Tuple[float, Dict[str, float]]:
    conn = connect(db_path)
    try:
        cash_row = conn.execute(
            "SELECT cash FROM proj_cash WHERE account_id=?", (account_id,)
        ).fetchone()
        cash = float(cash_row[0]) if cash_row else 0.0
        pos_rows = conn.execute(
            "SELECT symbol, qty FROM proj_positions WHERE account_id=?",
            (account_id,),
        ).fetchall()
        positions = {r[0]: float(r[1]) for r in pos_rows}
        return cash, positions
    finally:
        conn.close()


def build_stream_fields(event_type: str, payload: str) -> Dict[str, str]:
    """Match the platform convention (OutboxRelay.toFields / market-data):
    the full envelope JSON under `event`, with `event_type`/`schema_version`
    exposed as separate fields.
    """
    schema_version = "1"
    try:
        node = json.loads(payload)
        if node.get("schema_version") is not None:
            schema_version = str(node["schema_version"])
    except (ValueError, TypeError):
        pass
    return {
        "event_type": event_type,
        "schema_version": schema_version,
        "event": payload,
    }
