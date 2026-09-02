"""Deterministic trade seeding + the single-delivery baseline.

`generate()` produces a fixed set of `LedgerUpdated.v1`-shaped envelopes (one
per trade) with unique, stable `event_id`s and self-consistent `cash_delta` /
`position_after` values. `baseline()` folds those events exactly once to give
the positions/cash the consumer projection MUST match after all injected faults
-- i.e. the state you'd get from a perfect, single-delivery run.
"""
from __future__ import annotations

import json
from typing import Dict, List, Tuple

ACCOUNT_ID = "acct_123"
SEED_CASH = 10_000.0

# (symbol, side, quantity, price)
TRADES = [
    ("AAPL", "BUY", 10, 100.0),
    ("MSFT", "BUY", 5, 200.0),
    ("AAPL", "BUY", 5, 110.0),
    ("MSFT", "SELL", 2, 210.0),
    ("AAPL", "SELL", 3, 120.0),
    ("MSFT", "BUY", 4, 190.0),
]


def _envelope(event_id: str, symbol: str, side: str, qty: float, price: float,
              cash_delta: float, position_after: float) -> dict:
    return {
        "event_id": event_id,
        "event_type": "LedgerUpdated",
        "schema_version": "1",
        "producer": "ledger-core",
        "data": {
            "account_id": ACCOUNT_ID,
            "symbol": symbol,
            "side": side,
            "quantity": qty,
            "price": price,
            "cash_delta": cash_delta,
            "position_after": position_after,
        },
    }


def generate() -> List[dict]:
    """Return outbox event rows: {event_id, event_type, payload(JSON str)}."""
    positions: Dict[str, float] = {}
    events: List[dict] = []
    for i, (symbol, side, qty, price) in enumerate(TRADES, start=1):
        notional = qty * price
        cash_delta = -notional if side == "BUY" else notional
        pos_delta = qty if side == "BUY" else -qty
        positions[symbol] = positions.get(symbol, 0.0) + pos_delta
        event_id = f"evt-{i:03d}"
        payload = json.dumps(
            _envelope(event_id, symbol, side, qty, price, cash_delta, positions[symbol])
        )
        events.append(
            {"event_id": event_id, "event_type": "LedgerUpdated", "payload": payload}
        )
    return events


def baseline(events: List[dict]) -> Tuple[float, Dict[str, float]]:
    """Fold each distinct event exactly once -> (cash, {symbol: qty})."""
    cash = SEED_CASH
    positions: Dict[str, float] = {}
    for e in events:
        data = json.loads(e["payload"])["data"]
        cash += data["cash_delta"]
        positions[data["symbol"]] = data["position_after"]
    return cash, positions
