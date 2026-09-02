"""Durable risk-state store (SQLite) — the Phase 6 idempotency backbone.

Design: the consumer's dedupe is a **naturally-idempotent projection**, not a
separate "have I seen this?" flag. Every consumed `LedgerUpdated.v1` is written
to `applied_events` with the envelope `event_id` as PRIMARY KEY via
`INSERT OR IGNORE`, so re-delivering the same event (at-least-once redelivery,
XAUTOCLAIM reclaim, or a full replay) is a no-op. Portfolio state (cash,
positions) is then **derived by SQL** over that deduped log rather than mutated
in place.

Because the log lives in a file, the property survives a process restart: a
fresh process reopens the same DB and already "knows" every applied event. This
is exactly the durable, restart-safe dedupe the Phase 5 scoping note reserved
for the real `cg:risk-engine` consumer — so the shipped service has the property,
not merely the design.
"""
from __future__ import annotations

import sqlite3
from typing import Dict, List, Optional, Tuple


class RiskStore:
    """SQLite-backed durable projection + latest-price cache."""

    def __init__(self, db_path: str = "risk_state.db") -> None:
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path, timeout=30.0)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS applied_events(
                event_id       TEXT PRIMARY KEY,   -- envelope event_id (dedupe key)
                account_id     TEXT NOT NULL,
                symbol         TEXT NOT NULL,
                side           TEXT,
                quantity       REAL,
                price          REAL,               -- trade price (fallback mark)
                cash_delta     REAL NOT NULL,
                position_after REAL NOT NULL,
                correlation_id TEXT,
                posted_at      TEXT
            );
            CREATE TABLE IF NOT EXISTS price_cache(
                symbol TEXT PRIMARY KEY,
                price  REAL NOT NULL
            );
            """
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # --- price cache (from market.ticks) --------------------------------
    def upsert_price(self, symbol: str, price: float) -> None:
        self._conn.execute(
            "INSERT INTO price_cache(symbol, price) VALUES(?,?) "
            "ON CONFLICT(symbol) DO UPDATE SET price=excluded.price",
            (symbol, price),
        )
        self._conn.commit()

    def get_price(self, symbol: str) -> Optional[float]:
        row = self._conn.execute(
            "SELECT price FROM price_cache WHERE symbol=?", (symbol,)
        ).fetchone()
        return float(row[0]) if row else None

    # --- ledger event log (idempotent by event_id) ----------------------
    def apply_ledger_event(self, event_id: str, account_id: str, symbol: str,
                           side: Optional[str], quantity: Optional[float],
                           price: Optional[float], cash_delta: float,
                           position_after: float, correlation_id: Optional[str],
                           posted_at: Optional[str]) -> bool:
        """Record one ledger event. Returns True if newly applied, False if a
        duplicate (already-seen event_id) — the strict, durable dedupe.
        """
        cur = self._conn.execute(
            "INSERT OR IGNORE INTO applied_events("
            "event_id, account_id, symbol, side, quantity, price, cash_delta, "
            "position_after, correlation_id, posted_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (event_id, account_id, symbol, side, quantity, price, cash_delta,
             position_after, correlation_id, posted_at),
        )
        self._conn.commit()
        return cur.rowcount == 1

    def already_applied(self, event_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM applied_events WHERE event_id=?", (event_id,)
        ).fetchone()
        return row is not None

    def applied_count(self) -> int:
        return int(
            self._conn.execute("SELECT COUNT(*) FROM applied_events").fetchone()[0]
        )

    # --- derived projection ---------------------------------------------
    def account_cash(self, account_id: str, seed_cash: float) -> float:
        """cash = seed + sum(cash_delta) over the deduped event log."""
        total = self._conn.execute(
            "SELECT COALESCE(SUM(cash_delta),0) FROM applied_events WHERE account_id=?",
            (account_id,),
        ).fetchone()[0]
        return seed_cash + float(total)

    def latest_positions(self, account_id: str) -> List[Tuple[str, float, float]]:
        """Latest (symbol, position_after, trade_price) per symbol for account.

        "Latest" = the most-recently inserted event for that symbol (max rowid),
        which is stream order. Derived, so it is inherently idempotent.
        """
        rows = self._conn.execute(
            "SELECT symbol, position_after, price FROM applied_events e "
            "WHERE account_id=? AND rowid=("
            "  SELECT MAX(rowid) FROM applied_events "
            "  WHERE account_id=e.account_id AND symbol=e.symbol) "
            "ORDER BY symbol",
            (account_id,),
        ).fetchall()
        return [(r[0], float(r[1]), float(r[2]) if r[2] is not None else 0.0)
                for r in rows]

    def resolved_positions(self, account_id: str) -> List[Tuple[str, float, float]]:
        """(symbol, qty, resolved_price) where resolved_price prefers the live
        market.ticks price and falls back to the trade price when no tick has
        arrived yet — so PV/PnL are meaningful before a market feed exists.
        """
        out: List[Tuple[str, float, float]] = []
        for symbol, qty, trade_price in self.latest_positions(account_id):
            mark = self.get_price(symbol)
            out.append((symbol, qty, mark if mark is not None else trade_price))
        return out

    def accounts(self) -> List[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT account_id FROM applied_events"
        ).fetchall()
        return [r[0] for r in rows]

    def price_map(self) -> Dict[str, float]:
        rows = self._conn.execute("SELECT symbol, price FROM price_cache").fetchall()
        return {r[0]: float(r[1]) for r in rows}
