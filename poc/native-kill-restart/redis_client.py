"""Redis client for the Phase 5 Task 5 proof.

Design decision (deliberate, and previously corrected twice on this project):
the entire job of this proof is to *prove* the reliability guarantee, so its
Redis access must be trustworthy. Hand-rolling a RESP protocol client for the
one component that talks to Redis is exactly the fragile pattern we already
reversed on the Go market-data service (hand-rolled RESP -> go-redis) and in
Task 3 (raw XAUTOCLAIM reply hand-parsing returned nothing -> switched to the
typed Spring Data APIs). A mis-parsed `XAUTOCLAIM`/`XPENDING` reply here could
make the proof report green without actually exercising the reclaim -- a false
proof, worse than no proof.

`redis-py` (8.x) is already importable in this environment (verified), so this
module is a thin adapter over that battle-tested client. It exposes exactly the
small, stream-focused surface the proof processes use, keeping protocol parsing
inside the library rather than in this repo.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import redis
from redis.exceptions import RedisError as _PyRedisError

# Re-exported so callers can `except RedisError` without importing redis directly.
RedisError = _PyRedisError

Entry = Tuple[str, Dict[str, Optional[str]]]  # (stream-id, {field: value})


def _to_str(v) -> str:
    if isinstance(v, (bytes, bytearray)):
        return v.decode("utf-8")
    return str(v)


def _decode_entry(e) -> Entry:
    """redis-py (decode_responses=True) yields (id, {field: value}) tuples.

    Normalize to (str-id, {str-field: str|None-value}) so the proof logic is
    independent of the client's exact string/bytes handling.
    """
    entry_id = _to_str(e[0])
    raw_fields = e[1] or {}
    fields: Dict[str, Optional[str]] = {}
    for k, val in raw_fields.items():
        fields[_to_str(k)] = _to_str(val) if val is not None else None
    return (entry_id, fields)


class Redis:
    """Thin, blocking wrapper over redis-py exposing only what the proof needs."""

    def __init__(self, host: str = "127.0.0.1", port: int = 6379,
                 timeout: float = 10.0) -> None:
        self.host = host
        self.port = port
        self._r = redis.Redis(
            host=host,
            port=port,
            socket_timeout=timeout,
            socket_connect_timeout=timeout,
            decode_responses=True,
        )

    # --- lifecycle -------------------------------------------------------
    def close(self) -> None:
        try:
            self._r.close()
        except _PyRedisError:
            pass

    # --- basic commands --------------------------------------------------
    def ping(self) -> str:
        return "PONG" if self._r.ping() else ""

    def delete(self, *keys: str) -> int:
        if not keys:
            return 0
        return int(self._r.delete(*keys))

    # --- streams: producer / inspection ----------------------------------
    def xadd(self, stream: str, fields: Dict[str, str]) -> str:
        # Preserve field order/values; redis-py handles RESP encoding.
        clean = {k: ("" if v is None else v) for k, v in fields.items()}
        return _to_str(self._r.xadd(stream, clean))

    def xlen(self, stream: str) -> int:
        return int(self._r.xlen(stream))

    def xrange(self, stream: str, start: str = "-", end: str = "+") -> List[Entry]:
        reply = self._r.xrange(stream, min=start, max=end)
        return [_decode_entry(e) for e in (reply or [])]

    # --- streams: consumer groups ----------------------------------------
    def xgroup_create(self, stream: str, group: str, start_id: str = "0",
                      mkstream: bool = True) -> None:
        try:
            self._r.xgroup_create(stream, group, id=start_id, mkstream=mkstream)
        except _PyRedisError as ex:
            # BUSYGROUP (already exists) is expected/fine for a proof.
            if "BUSYGROUP" not in str(ex):
                raise

    def xgroup_destroy(self, stream: str, group: str) -> int:
        try:
            return int(self._r.xgroup_destroy(stream, group))
        except _PyRedisError:
            return 0

    def xreadgroup(self, group: str, consumer: str, stream: str,
                   count: int = 1) -> List[Entry]:
        """Read *new* entries (`>`). Returns [] when none are pending for us."""
        reply = self._r.xreadgroup(group, consumer, {stream: ">"}, count=count)
        if not reply:
            return []
        out: List[Entry] = []
        for _stream_name, entries in reply:
            for e in entries or []:
                out.append(_decode_entry(e))
        return out

    def xack(self, stream: str, group: str, *ids: str) -> int:
        if not ids:
            return 0
        return int(self._r.xack(stream, group, *ids))

    def xpending_count(self, stream: str, group: str) -> int:
        """XPENDING summary -> number of un-acked entries for the group."""
        summary = self._r.xpending(stream, group)
        if not summary:
            return 0
        # redis-py returns a dict with a 'pending' count in summary form.
        return int(summary.get("pending", 0))

    def xautoclaim(self, stream: str, group: str, consumer: str,
                   min_idle_ms: int, start: str = "0",
                   count: int = 100) -> Tuple[str, List[Entry]]:
        """Reclaim idle pending entries (XAUTOCLAIM) via redis-py.

        redis-py returns `[next_cursor, [(id, {fields}), ...], [deleted_ids]]`
        (the deleted list is absent on older servers); we surface
        (next-cursor, entries).
        """
        reply = self._r.xautoclaim(
            stream, group, consumer, min_idle_time=min_idle_ms,
            start_id=start, count=count,
        )
        if not reply:
            return ("0-0", [])
        cursor = _to_str(reply[0])
        raw_entries = reply[1] if len(reply) > 1 else []
        entries: List[Entry] = []
        for e in raw_entries or []:
            # Deleted entries can surface with nil fields; skip those.
            if e is None or e[1] is None:
                continue
            entries.append(_decode_entry(e))
        return (cursor, entries)
