"""Run the whole-project TradePulse pipeline end-to-end and assert acceptance criteria.

Flow: market-data -> ledger-core (outbox) -> relay -> risk-engine -> gateway.
Reuses the proven modules from ../outbox-idempotency (StreamBus, Ledger, relay).

Run:
    python run_pipeline.py
"""
from __future__ import annotations

import os
import sys

# Reuse the proven correctness-core modules from the sibling POC.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, os.pardir, "outbox-idempotency"))
sys.path.insert(0, _HERE)

from gateway import Gateway  # noqa: E402
from ledger import Ledger  # noqa: E402
from market_data import produce_ticks  # noqa: E402
from relay import relay_outbox  # noqa: E402
from risk_engine import PriceCache, RiskEngine  # noqa: E402
from stream_bus import StreamBus  # noqa: E402

CORR = "corr-e2e-1"


def trade_request(request_id: str, price: float, side: str = "BUY", qty: float = 10) -> dict:
    """A TradeRequested.v1 payload (REST body to ledger-core)."""
    return {
        "request_id": request_id,
        "account_id": "acct_123",
        "symbol": "AAPL",
        "side": side,
        "quantity": qty,
        "price": price,
        "requested_by": "user_42",
        "correlation_id": CORR,
    }


def main() -> int:
    bus = StreamBus()
    ledger = Ledger()
    cache = PriceCache(bus)
    risk = RiskEngine(bus, cache)
    gw = Gateway(bus)

    # 1) market-data emits ticks; risk-engine caches latest price.
    ticks = produce_ticks(bus, [100.0, 101.0, 102.5, 101.5, 103.0], CORR)
    cache.refresh()

    # 2) trades posted through the ledger (atomic double-entry + outbox row).
    latest_price = cache.latest["AAPL"]
    for rid in ("t1", "t2", "t3"):
        ledger.post_trade(trade_request(rid, price=latest_price))
    # 3) relay drains the outbox to ledger.updates (at-least-once).
    published = relay_outbox(ledger, bus)

    # 4) risk-engine reacts (idempotent) and emits RiskComputed; 5) gateway fans out.
    risk.poll()
    gw.pump()

    print("ticks_produced        =", ticks)
    print("prices_cached         =", cache.latest)
    print("ledger je_count       =", ledger.je_count(), "| published =", published)
    print("risk applied/skipped  =", risk.applied, "/", risk.skipped)
    print("stream lengths        = ticks:", bus.stream_len("market.ticks"),
          "ledger:", bus.stream_len("ledger.updates"),
          "risk:", bus.stream_len("risk.updates"))
    print("gateway pushed types  =", sorted(gw.pushed_types()), "| count =", len(gw.pushed))

    # ---- Acceptance criteria ----
    assert bus.stream_len("market.ticks") == ticks, "all ticks must be on market.ticks"
    assert ledger.je_count() == 3 and bus.stream_len("ledger.updates") == 3, \
        "each posted trade -> exactly one LedgerUpdated via outbox"
    assert bus.stream_len("risk.updates") == 3, "risk-engine emits RiskComputed per change"
    assert risk.applied == 3 and risk.skipped == 0, "each ledger event applied once"
    streamed_types = {
        e[1]["event_type"]
        for s in ("market.ticks", "ledger.updates", "risk.updates")
        for e in bus.streams[s]
    }
    assert streamed_types == {"TickReceived", "LedgerUpdated", "RiskComputed"}, streamed_types
    assert gw.pushed_types() == {"TickReceived", "RiskComputed"}, gw.pushed_types()
    ledger.assert_double_entry()

    # ---- Resilience pass: duplicate + full replay must not change derived state ----
    positions_before = dict(risk.pos)
    # inject a duplicate of the last ledger event and a replay from the start
    bus.xadd("ledger.updates", bus.streams["ledger.updates"][-1][1])
    bus.setid("ledger.updates", "cg:risk-engine", 0)
    risk.poll()
    assert risk.pos == positions_before, "duplicate/replay must not change positions"
    assert risk.skipped >= 3, "replayed + duplicated events must be deduped"
    print("resilience: positions stable after duplicate+replay; skipped =", risk.skipped)

    print("\nEND-TO-END PIPELINE PASSED")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as e:
        print("\nPIPELINE FAILED:", e)
        sys.exit(1)
