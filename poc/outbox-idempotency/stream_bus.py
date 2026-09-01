"""In-process approximation of Redis Streams for the POC.

Models the delivery semantics we depend on:
- append-only entries per stream (XADD)
- consumer groups with a last-delivered id and a Pending Entries List (PEL)
- XREADGROUP (delivers new entries, tracks them as pending)
- XACK (removes from PEL)
- redelivery of unacked entries after a simulated consumer crash
- SETID-style replay (reset a group's cursor to reprocess from the start)

This is deliberately synchronous and single-process so the correctness proof is
deterministic. It is NOT a performance model.
"""
from __future__ import annotations

from typing import Any


class StreamBus:
    def __init__(self) -> None:
        self.streams: dict[str, list[tuple[int, dict]]] = {}
        self.groups: dict[tuple[str, str], dict[str, Any]] = {}

    # --- producer side ---
    def xadd(self, stream: str, entry: dict) -> int:
        self.streams.setdefault(stream, [])
        eid = len(self.streams[stream]) + 1
        self.streams[stream].append((eid, entry))
        return eid

    def stream_len(self, stream: str) -> int:
        return len(self.streams.get(stream, []))

    # --- consumer-group management ---
    def xgroup_create(self, stream: str, group: str, start: int = 0) -> None:
        self.streams.setdefault(stream, [])
        self.groups[(stream, group)] = {"last": start, "pel": {}}

    def xreadgroup(self, stream: str, group: str, count: int = 10) -> list[tuple[int, dict]]:
        g = self.groups[(stream, group)]
        out: list[tuple[int, dict]] = []
        for eid, entry in self.streams[stream]:
            if eid > g["last"]:
                g["pel"][eid] = entry
                g["last"] = eid
                out.append((eid, entry))
                if len(out) >= count:
                    break
        return out

    def xack(self, stream: str, group: str, eid: int) -> None:
        self.groups[(stream, group)]["pel"].pop(eid, None)

    def xpending(self, stream: str, group: str) -> dict[int, dict]:
        return dict(self.groups[(stream, group)]["pel"])

    def redeliver_pending(self, stream: str, group: str) -> list[tuple[int, dict]]:
        """Simulate XAUTOCLAIM/XCLAIM: redeliver everything still in the PEL."""
        return list(self.groups[(stream, group)]["pel"].items())

    def setid(self, stream: str, group: str, start: int = 0) -> None:
        """Simulate XGROUP SETID for replay (reset cursor + clear PEL)."""
        self.groups[(stream, group)] = {"last": start, "pel": {}}
