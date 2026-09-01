"""Outbox relay publisher.

Drains unsent outbox rows to the stream and marks them sent. On restart it simply
re-drains whatever is still unsent, giving at-least-once publication. `inject_dup`
lets scenarios force a duplicate delivery to exercise consumer idempotency.
"""
from __future__ import annotations

import json

from ledger import Ledger
from stream_bus import StreamBus


def relay_outbox(
    ledger: Ledger, bus: StreamBus, stream: str = "ledger.updates", inject_dup: bool = False
) -> int:
    published = 0
    for event_id, payload in ledger.unsent_outbox():
        bus.xadd(stream, json.loads(payload))
        if inject_dup:
            bus.xadd(stream, json.loads(payload))  # simulate at-least-once duplicate
        ledger.mark_sent(event_id)
        published += 1
    return published
