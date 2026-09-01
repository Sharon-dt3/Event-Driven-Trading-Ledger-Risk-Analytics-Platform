"""Idempotent consumer (stand-in for the risk engine).

Dedupes by envelope `event_id` and only ACKs after applying effects, so duplicate
delivery and full replay are both safe. In production the `seen` set is a durable
processed-events table (UNIQUE event_id) rather than in-memory state.
"""
from __future__ import annotations

from stream_bus import StreamBus


class RiskConsumer:
    def __init__(
        self, bus: StreamBus, stream: str = "ledger.updates", group: str = "cg:risk-engine"
    ) -> None:
        self.bus = bus
        self.stream = stream
        self.group = group
        self.seen: set[str] = set()             # dedupe by event_id
        self.position_view: dict[tuple, float] = {}  # derived state
        self.applied = 0
        self.skipped = 0
        bus.xgroup_create(stream, group, 0)

    def _apply(self, eid: int, evt: dict) -> None:
        if evt["event_id"] in self.seen:
            self.skipped += 1
            self.bus.xack(self.stream, self.group, eid)
            return
        d = evt["data"]
        self.position_view[(d["account_id"], d["symbol"])] = d["position_after"]
        self.seen.add(evt["event_id"])
        self.applied += 1
        self.bus.xack(self.stream, self.group, eid)

    def poll(self, crash_before_ack: bool = False) -> str:
        for eid, evt in self.bus.xreadgroup(self.stream, self.group):
            if crash_before_ack:
                # Simulate a crash: entry stays in the PEL (unacked).
                return "crashed_before_ack"
            self._apply(eid, evt)
        return "ok"

    def recover(self) -> None:
        """Reclaim and reprocess pending (unacked) entries after a crash."""
        for eid, evt in self.bus.redeliver_pending(self.stream, self.group):
            self._apply(eid, evt)
