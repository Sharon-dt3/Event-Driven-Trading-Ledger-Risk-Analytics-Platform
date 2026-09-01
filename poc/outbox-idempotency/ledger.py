"""Double-entry ledger with a transactional outbox (SQLite for the POC).

Key correctness properties implemented here:
- The trade posting AND the outbox row are written in ONE local transaction,
  so they commit or roll back atomically (kills the dual-write problem).
- `source_event_id` is UNIQUE, so retried requests never double-post.
- Balances/positions are derived from balanced journal lines (double-entry).
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CrashInjected(Exception):
    """Raised to simulate a process crash at a chosen point."""


class Ledger:
    def __init__(self, path: str = ":memory:") -> None:
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA foreign_keys=ON")
        self._schema()

    def _schema(self) -> None:
        self.db.executescript(
            """
            CREATE TABLE accounts(account_id TEXT PRIMARY KEY, cash REAL NOT NULL DEFAULT 0);
            CREATE TABLE journal_entries(
                je_id TEXT PRIMARY KEY,
                source_event_id TEXT UNIQUE NOT NULL,   -- idempotency key (== request_id)
                posted_at TEXT NOT NULL);
            CREATE TABLE journal_lines(
                id INTEGER PRIMARY KEY AUTOINCREMENT, je_id TEXT NOT NULL,
                account_id TEXT NOT NULL, debit REAL NOT NULL DEFAULT 0, credit REAL NOT NULL DEFAULT 0);
            CREATE TABLE positions(
                account_id TEXT, symbol TEXT, qty REAL NOT NULL DEFAULT 0,
                PRIMARY KEY(account_id, symbol));
            CREATE TABLE audit_log(
                audit_id TEXT PRIMARY KEY, source_event_id TEXT, outcome TEXT, reason TEXT, recorded_at TEXT);
            CREATE TABLE outbox_events(
                event_id TEXT PRIMARY KEY, event_type TEXT, payload TEXT,
                sent INTEGER NOT NULL DEFAULT 0, created_at TEXT);
            """
        )
        self.db.execute("INSERT INTO accounts VALUES(?,?)", ("acct_123", 10000.0))
        self.db.commit()

    def post_trade(self, req: dict, crash_point: str | None = None) -> dict:
        """Post a filled trade atomically with its outbox event.

        crash_point in {None, "before_commit", "after_commit_before_publish"}.
        """
        cur = self.db.cursor()

        # Idempotency: a retried request_id short-circuits (no double-post).
        row = cur.execute(
            "SELECT je_id FROM journal_entries WHERE source_event_id=?",
            (req["request_id"],),
        ).fetchone()
        if row:
            return {"status": "posted", "je_id": row[0], "idempotent_replay": True}

        cash = cur.execute(
            "SELECT cash FROM accounts WHERE account_id=?", (req["account_id"],)
        ).fetchone()[0]
        cash_delta = (
            -req["quantity"] * req["price"]
            if req["side"] == "BUY"
            else req["quantity"] * req["price"]
        )

        # Compliance: no negative cash. Rejections are still audited.
        if cash + cash_delta < 0:
            cur.execute(
                "INSERT INTO audit_log VALUES(?,?,?,?,?)",
                (str(uuid.uuid4()), req["request_id"], "rejected", "NEGATIVE_CASH", now()),
            )
            self.db.commit()
            return {"status": "rejected", "reason": "NEGATIVE_CASH"}

        try:
            je = str(uuid.uuid4())
            cur.execute(
                "INSERT INTO journal_entries VALUES(?,?,?)",
                (je, req["request_id"], now()),
            )
            # Double-entry: mirrored debit/credit lines (securities vs cash account).
            amount = abs(cash_delta)
            if req["side"] == "BUY":
                lines = [("securities", amount, 0.0), (req["account_id"], 0.0, amount)]
            else:
                lines = [(req["account_id"], amount, 0.0), ("securities", 0.0, amount)]
            for acct, debit, credit in lines:
                cur.execute(
                    "INSERT INTO journal_lines(je_id,account_id,debit,credit) VALUES(?,?,?,?)",
                    (je, acct, debit, credit),
                )

            cur.execute(
                "UPDATE accounts SET cash=cash+? WHERE account_id=?",
                (cash_delta, req["account_id"]),
            )
            qd = req["quantity"] if req["side"] == "BUY" else -req["quantity"]
            cur.execute(
                "INSERT INTO positions(account_id,symbol,qty) VALUES(?,?,?) "
                "ON CONFLICT(account_id,symbol) DO UPDATE SET qty=qty+?",
                (req["account_id"], req["symbol"], qd, qd),
            )
            cur.execute(
                "INSERT INTO audit_log VALUES(?,?,?,?,?)",
                (str(uuid.uuid4()), req["request_id"], "accepted", None, now()),
            )
            pos = cur.execute(
                "SELECT qty FROM positions WHERE account_id=? AND symbol=?",
                (req["account_id"], req["symbol"]),
            ).fetchone()[0]

            # SAME transaction: write the outbox event (intent to publish).
            event_id = str(uuid.uuid4())
            evt = {
                "event_id": event_id,
                "event_type": "LedgerUpdated",
                "schema_version": "1",
                "correlation_id": req.get("correlation_id", str(uuid.uuid4())),
                "produced_at": now(),
                "producer": "ledger-core",
                "data": {
                    "journal_entry_id": je,
                    "source_event_id": req["request_id"],
                    "account_id": req["account_id"],
                    "symbol": req["symbol"],
                    "side": req["side"],
                    "quantity": req["quantity"],
                    "price": req["price"],
                    "cash_delta": cash_delta,
                    "position_after": pos,
                    "posted_at": now(),
                },
            }
            cur.execute(
                "INSERT INTO outbox_events VALUES(?,?,?,?,?)",
                (event_id, "LedgerUpdated", json.dumps(evt), 0, now()),
            )

            if crash_point == "before_commit":
                raise CrashInjected("crash after writes, before COMMIT")

            self.db.commit()
        except CrashInjected:
            self.db.rollback()  # atomic: trade AND outbox row both vanish
            raise

        if crash_point == "after_commit_before_publish":
            # DB is durable; process dies before the relay runs.
            raise CrashInjected("crash after COMMIT, before publish")

        return {"status": "posted", "je_id": je, "event_id": event_id}

    # --- outbox helpers (used by the relay) ---
    def unsent_outbox(self) -> list[tuple[str, str]]:
        return self.db.execute(
            "SELECT event_id,payload FROM outbox_events WHERE sent=0 ORDER BY rowid"
        ).fetchall()

    def mark_sent(self, event_id: str) -> None:
        self.db.execute("UPDATE outbox_events SET sent=1 WHERE event_id=?", (event_id,))
        self.db.commit()

    # --- read helpers / invariants ---
    def assert_double_entry(self) -> tuple[float, float]:
        d, c = self.db.execute(
            "SELECT COALESCE(SUM(debit),0),COALESCE(SUM(credit),0) FROM journal_lines"
        ).fetchone()
        assert abs(d - c) < 1e-9, f"double-entry violated: debits={d} credits={c}"
        return d, c

    def cash(self, account_id: str = "acct_123") -> float:
        return self.db.execute(
            "SELECT cash FROM accounts WHERE account_id=?", (account_id,)
        ).fetchone()[0]

    def position(self, account_id: str, symbol: str) -> float:
        r = self.db.execute(
            "SELECT qty FROM positions WHERE account_id=? AND symbol=?",
            (account_id, symbol),
        ).fetchone()
        return r[0] if r else 0

    def je_count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM journal_entries").fetchone()[0]
