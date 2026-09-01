"""Market-data producer (POC stand-in for services/market-data).

Emits TickReceived.v1 envelopes onto the `market.ticks` stream.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def envelope(event_type: str, producer: str, data: dict, correlation_id: str) -> dict:
    """Build an event envelope matching docs/contracts/events/envelope.schema.json."""
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "schema_version": "1",
        "correlation_id": correlation_id,
        "produced_at": now(),
        "producer": producer,
        "data": data,
    }


def produce_ticks(bus, prices, correlation_id: str, symbol: str = "AAPL") -> int:
    """Append one TickReceived.v1 per price to `market.ticks`."""
    for price in prices:
        bus.xadd(
            "market.ticks",
            envelope(
                "TickReceived",
                "market-data",
                {
                    "symbol": symbol,
                    "price": price,
                    "volume": 100,
                    "source": "synthetic",
                    "tick_time": now(),
                },
                correlation_id,
            ),
        )
    return len(prices)
