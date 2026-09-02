"""Risk-engine consumer core (Redis-free, unit-testable).

This module owns the *decision* logic — parse an envelope, durably dedupe +
apply it to the projection, recompute metrics, and build the outgoing
`RiskComputed.v1` envelope — with no Redis dependency. The actual stream I/O
(XREADGROUP / XACK / XAUTOCLAIM / XADD) lives in `worker.py`, mirroring the
ledger-core split where `Phase5PocConsumer.handle()` is broker-free.

Recompute strategy (2A): metrics are recomputed and published on each applied
`ledger.updates` event. `market.ticks` only refresh the latest-price cache; they
do not themselves trigger a publish in this thin slice.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .config import Config
from .metrics import compute_metrics
from .store import RiskStore


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RiskConsumer:
    """Applies ledger/tick events to the durable store and builds risk events."""

    def __init__(self, store: RiskStore, config: Config) -> None:
        self.store = store
        self.config = config

    # --- market.ticks: refresh latest-price cache -----------------------
    def process_tick_envelope(self, envelope: Dict[str, Any]) -> bool:
        """Update the latest-price cache from a TickReceived.v1 envelope.

        :returns: True if a price was recorded, False if the event was malformed.
        """
        data = envelope.get("data") or {}
        symbol = data.get("symbol")
        price = data.get("price")
        if not symbol or price is None:
            return False
        try:
            self.store.upsert_price(symbol, float(price))
        except (TypeError, ValueError):
            return False
        return True

    # --- ledger.updates: dedupe, apply, recompute, build risk event -----
    def process_ledger_envelope(self, envelope: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Durably apply a LedgerUpdated.v1 envelope and, if newly applied,
        return a RiskComputed.v1 envelope to publish. Duplicates return None.
        """
        event_id = envelope.get("event_id")
        data = envelope.get("data") or {}
        account_id = data.get("account_id")
        symbol = data.get("symbol")
        if not event_id or not account_id or not symbol:
            return None  # malformed; skip safely

        cash_delta = data.get("cash_delta")
        position_after = data.get("position_after")
        if cash_delta is None or position_after is None:
            return None

        correlation_id = envelope.get("correlation_id")

        newly_applied = self.store.apply_ledger_event(
            event_id=event_id,
            account_id=account_id,
            symbol=symbol,
            side=data.get("side"),
            quantity=_as_float(data.get("quantity")),
            price=_as_float(data.get("price")),
            cash_delta=float(cash_delta),
            position_after=float(position_after),
            correlation_id=correlation_id,
            posted_at=data.get("posted_at"),
        )
        if not newly_applied:
            return None  # strict, durable dedupe: no double-apply, no double-publish

        return self._build_risk_envelope(account_id, correlation_id)

    def _build_risk_envelope(self, account_id: str,
                             correlation_id: Optional[str]) -> Dict[str, Any]:
        cash = self.store.account_cash(account_id, self.config.seed_cash)
        positions = self.store.resolved_positions(account_id)
        metrics = compute_metrics(cash, positions, self.config.seed_cash)

        return {
            "event_id": str(uuid.uuid4()),
            "event_type": "RiskComputed",
            "schema_version": "1",
            "correlation_id": correlation_id or str(uuid.uuid4()),
            "produced_at": _now_iso(),
            "producer": "risk-engine",
            "data": {
                "account_id": account_id,
                "portfolio_value": metrics.portfolio_value,
                "pnl": metrics.pnl,
                "volatility": metrics.volatility,
                "var": metrics.var,
                "var_method": metrics.var_method,
                "sharpe": metrics.sharpe,
                "computed_at": _now_iso(),
            },
        }

    @staticmethod
    def stream_fields(envelope: Dict[str, Any]) -> Dict[str, str]:
        """Build Redis stream entry fields matching the platform convention:
        full envelope JSON under `event`, with type/version exposed separately.
        """
        return {
            "event_type": envelope["event_type"],
            "schema_version": envelope["schema_version"],
            "event": json.dumps(envelope),
        }


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
