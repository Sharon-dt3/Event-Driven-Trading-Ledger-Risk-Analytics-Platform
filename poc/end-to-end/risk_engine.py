"""Risk engine (POC stand-in for services/risk-engine).

- Maintains a latest-price cache from `market.ticks`.
- Idempotently consumes `ledger.updates` (dedupe by event_id) and, on each change,
  recomputes portfolio metrics and emits RiskComputed.v1 to `risk.updates`.

Metrics are simplified but structurally faithful (see README section 4).
"""
from __future__ import annotations

import statistics

from market_data import envelope

STREAM_TICKS = "market.ticks"
STREAM_LEDGER = "ledger.updates"
STREAM_RISK = "risk.updates"
GROUP = "cg:risk-engine"
SEED_CASH = 10000.0


class PriceCache:
    """Latest price per symbol, sourced from market.ticks."""

    def __init__(self, bus) -> None:
        self.bus = bus
        self.latest: dict[str, float] = {}
        bus.xgroup_create(STREAM_TICKS, GROUP, 0)

    def refresh(self) -> dict[str, float]:
        for eid, evt in self.bus.xreadgroup(STREAM_TICKS, GROUP):
            d = evt["data"]
            self.latest[d["symbol"]] = d["price"]
            self.bus.xack(STREAM_TICKS, GROUP, eid)
        return dict(self.latest)


class RiskEngine:
    def __init__(self, bus, cache: PriceCache) -> None:
        self.bus = bus
        self.cache = cache
        self.seen: set[str] = set()
        self.pos: dict[str, float] = {}
        self.cost: dict[str, float] = {}
        self.returns: list[float] = []
        self.last_pv: float | None = None
        self.applied = 0
        self.skipped = 0
        bus.xgroup_create(STREAM_LEDGER, GROUP, 0)

    def poll(self) -> None:
        for eid, evt in self.bus.xreadgroup(STREAM_LEDGER, GROUP):
            self._apply(eid, evt)

    def replay_pending(self) -> None:
        """Reprocess redelivered/pending entries (idempotent)."""
        for eid, evt in self.bus.xreadgroup(STREAM_LEDGER, GROUP):
            self._apply(eid, evt)

    def _apply(self, eid: int, evt: dict) -> None:
        if evt["event_id"] in self.seen:
            self.skipped += 1
            self.bus.xack(STREAM_LEDGER, GROUP, eid)
            return
        d = evt["data"]
        self.pos[d["symbol"]] = d["position_after"]
        # cost basis accumulates cash outflow (negative cash_delta on BUY)
        self.cost[d["symbol"]] = self.cost.get(d["symbol"], 0.0) + (-d["cash_delta"])
        self.seen.add(evt["event_id"])
        self.applied += 1
        self.bus.xack(STREAM_LEDGER, GROUP, eid)
        self._compute(d["account_id"], evt["correlation_id"])

    def _compute(self, account_id: str, correlation_id: str) -> None:
        symbol = "AAPL"
        price = self.cache.latest.get(symbol, 0.0)
        qty = self.pos.get(symbol, 0.0)
        market_value = qty * price
        cost = self.cost.get(symbol, 0.0)
        pnl = market_value - cost
        pv = SEED_CASH + pnl
        if self.last_pv:
            self.returns.append((pv - self.last_pv) / self.last_pv)
        self.last_pv = pv
        vol = statistics.pstdev(self.returns) if len(self.returns) > 1 else 0.0
        var = 1.65 * vol * pv  # parametric (~95% one-sided), Phase 0 default
        sharpe = (statistics.mean(self.returns) / vol) if vol > 0 else 0.0
        self.bus.xadd(
            STREAM_RISK,
            envelope(
                "RiskComputed",
                "risk-engine",
                {
                    "account_id": account_id,
                    "portfolio_value": round(pv, 2),
                    "pnl": round(pnl, 2),
                    "volatility": round(vol, 6),
                    "var": round(abs(var), 2),
                    "var_method": "parametric",
                    "sharpe": round(sharpe, 4),
                    "computed_at": __import__("datetime").datetime.now(
                        __import__("datetime").timezone.utc
                    ).isoformat(),
                },
                correlation_id,
            ),
        )
