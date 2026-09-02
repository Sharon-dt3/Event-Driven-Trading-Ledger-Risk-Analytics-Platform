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
            CREATE TABLE IF NOT EXISTS price_history(
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol    TEXT NOT NULL,
                price     REAL NOT NULL,
                tick_time TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_price_history_symbol
                ON price_history(symbol, id);
            CREATE TABLE IF NOT EXISTS pv_history(
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id  TEXT NOT NULL,
                pv          REAL NOT NULL,
                computed_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_pv_history_account
                ON pv_history(account_id, id);
            CREATE TABLE IF NOT EXISTS risk_snapshots(
                account_id      TEXT PRIMARY KEY,   -- latest published snapshot
                portfolio_value REAL NOT NULL,
                pnl             REAL NOT NULL,
                volatility      REAL NOT NULL,
                var             REAL NOT NULL,
                var_method      TEXT NOT NULL,
                sharpe          REAL NOT NULL,
                computed_at     TEXT NOT NULL
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

    # --- rolling price history (from market.ticks; foundation for stats) --
    def append_price(self, symbol: str, price: float, window_size: int,
                     tick_time: Optional[str] = None) -> None:
        """Append one tick price to the per-symbol rolling window, then evict
        anything older than the most recent ``window_size + 1`` prices (so up to
        ``window_size`` returns can be derived). Durable and idempotent-safe to
        replay in the sense that duplicates simply extend the window and are
        evicted; metric math consumes only the retained tail.
        """
        keep = max(int(window_size), 0) + 1
        self._conn.execute(
            "INSERT INTO price_history(symbol, price, tick_time) VALUES(?,?,?)",
            (symbol, float(price), tick_time),
        )
        self._conn.execute(
            "DELETE FROM price_history WHERE symbol=? AND id NOT IN ("
            "  SELECT id FROM price_history WHERE symbol=? ORDER BY id DESC LIMIT ?)",
            (symbol, symbol, keep),
        )
        self._conn.commit()

    def price_window(self, symbol: str) -> List[float]:
        """Retained prices for a symbol, ordered oldest -> newest."""
        rows = self._conn.execute(
            "SELECT price FROM ("
            "  SELECT id, price FROM price_history WHERE symbol=? ORDER BY id DESC"
            ") ORDER BY id ASC",
            (symbol,),
        ).fetchall()
        return [float(r[0]) for r in rows]

    def history_len(self, symbol: str) -> int:
        return int(
            self._conn.execute(
                "SELECT COUNT(*) FROM price_history WHERE symbol=?", (symbol,)
            ).fetchone()[0]
        )

    def returns(self, symbol: str) -> List[float]:
        """Simple consecutive returns r_i = (p_i - p_{i-1}) / p_{i-1} over the
        retained window, ordered oldest -> newest. For N retained prices this is
        N-1 returns; a zero previous price is skipped defensively.
        """
        prices = self.price_window(symbol)
        out: List[float] = []
        for prev, cur in zip(prices, prices[1:]):
            if prev == 0:
                continue
            out.append((cur - prev) / prev)
        return out

    # --- rolling portfolio-value history (model A: metric return series) --
    def append_pv(self, account_id: str, pv: float, window_size: int,
                  computed_at: Optional[str] = None) -> None:
        """Append one portfolio-value snapshot to the per-account rolling window
        (sampled by the 2B throttle), then evict to the most recent
        ``window_size + 1`` snapshots so up to ``window_size`` PV returns derive.
        Durable and restart-safe, mirroring the price-history plumbing.
        """
        keep = max(int(window_size), 0) + 1
        self._conn.execute(
            "INSERT INTO pv_history(account_id, pv, computed_at) VALUES(?,?,?)",
            (account_id, float(pv), computed_at),
        )
        self._conn.execute(
            "DELETE FROM pv_history WHERE account_id=? AND id NOT IN ("
            "  SELECT id FROM pv_history WHERE account_id=? ORDER BY id DESC LIMIT ?)",
            (account_id, account_id, keep),
        )
        self._conn.commit()

    def pv_window(self, account_id: str) -> List[float]:
        """Retained PV snapshots for an account, ordered oldest -> newest."""
        rows = self._conn.execute(
            "SELECT pv FROM ("
            "  SELECT id, pv FROM pv_history WHERE account_id=? ORDER BY id DESC"
            ") ORDER BY id ASC",
            (account_id,),
        ).fetchall()
        return [float(r[0]) for r in rows]

    def pv_history_len(self, account_id: str) -> int:
        return int(
            self._conn.execute(
                "SELECT COUNT(*) FROM pv_history WHERE account_id=?", (account_id,)
            ).fetchone()[0]
        )

    def pv_returns(self, account_id: str) -> List[float]:
        """Simple consecutive PV returns r_i = (pv_i - pv_{i-1}) / pv_{i-1} over
        the retained snapshots, ordered oldest -> newest (N snapshots -> N-1
        returns; a zero previous PV is skipped defensively).
        """
        pvs = self.pv_window(account_id)
        out: List[float] = []
        for prev, cur in zip(pvs, pvs[1:]):
            if prev == 0:
                continue
            out.append((cur - prev) / prev)
        return out

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

    # --- latest risk snapshot (backs the REST read API) -----------------
    def save_risk_snapshot(self, account_id: str, portfolio_value: float,
                           pnl: float, volatility: float, var: float,
                           var_method: str, sharpe: float,
                           computed_at: str) -> None:
        """Upsert the latest computed risk snapshot for an account.

        Written as each ``RiskComputed.v1`` is built (and immediately published),
        so ``GET /risk/summary`` / ``GET /risk/var`` serve exactly what was last
        put on ``risk.updates`` — the fetch-on-load stays coherent with the
        live stream.
        """
        self._conn.execute(
            "INSERT INTO risk_snapshots("
            "account_id, portfolio_value, pnl, volatility, var, var_method, "
            "sharpe, computed_at) VALUES(?,?,?,?,?,?,?,?) "
            "ON CONFLICT(account_id) DO UPDATE SET "
            "portfolio_value=excluded.portfolio_value, pnl=excluded.pnl, "
            "volatility=excluded.volatility, var=excluded.var, "
            "var_method=excluded.var_method, sharpe=excluded.sharpe, "
            "computed_at=excluded.computed_at",
            (account_id, float(portfolio_value), float(pnl), float(volatility),
             float(var), var_method, float(sharpe), computed_at),
        )
        self._conn.commit()

    def get_risk_snapshot(self, account_id: str) -> Optional[Dict[str, object]]:
        """Latest snapshot for an account (contract ``RiskSummary`` shape), or
        None when nothing has been computed yet (→ REST 404).
        """
        row = self._conn.execute(
            "SELECT account_id, portfolio_value, pnl, volatility, var, "
            "var_method, sharpe, computed_at FROM risk_snapshots WHERE account_id=?",
            (account_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "account_id": row[0],
            "portfolio_value": float(row[1]),
            "pnl": float(row[2]),
            "volatility": float(row[3]),
            "var": float(row[4]),
            "var_method": row[5],
            "sharpe": float(row[6]),
            "computed_at": row[7],
        }
