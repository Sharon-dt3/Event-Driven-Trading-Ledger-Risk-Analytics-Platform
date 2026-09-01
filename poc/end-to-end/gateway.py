"""Realtime gateway (POC stand-in for services/gateway).

Idempotently consumes `market.ticks` + `risk.updates` and 'pushes' them to
connected clients. Dedupe by event_id so redelivery/replay never double-pushes.
"""
from __future__ import annotations

STREAM_TICKS = "market.ticks"
STREAM_RISK = "risk.updates"
GROUP = "cg:gateway"


class Gateway:
    def __init__(self, bus) -> None:
        self.bus = bus
        self.seen: set[str] = set()
        self.pushed: list[tuple[str, str]] = []  # (event_type, account_or_symbol)
        bus.xgroup_create(STREAM_TICKS, GROUP, 0)
        bus.xgroup_create(STREAM_RISK, GROUP, 0)

    def pump(self) -> None:
        for stream in (STREAM_TICKS, STREAM_RISK):
            for eid, evt in self.bus.xreadgroup(stream, GROUP):
                if evt["event_id"] not in self.seen:
                    self.seen.add(evt["event_id"])
                    label = evt["data"].get("symbol") or evt["data"].get("account_id", "")
                    self.pushed.append((evt["event_type"], label))
                self.bus.xack(stream, GROUP, eid)

    def pushed_types(self) -> set[str]:
        return {t for t, _ in self.pushed}
