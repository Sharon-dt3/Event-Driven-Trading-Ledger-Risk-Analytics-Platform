#!/usr/bin/env python3
"""Killable idempotent consumer process (Phase 5 Task 3, native).

Reads `ledger.updates` via XREADGROUP on the throwaway group `cg:phase5-poc`,
dedupes strictly by envelope `event_id` (durably, in SQLite -- see store.py),
applies a trivial positions/cash projection, then XACKs. Each cycle it FIRST
reclaims stale pending entries via XAUTOCLAIM and reprocesses them; dedupe makes
an already-applied reclaim a no-op. This mirrors `Phase5PocConsumer`.

Kill point: `--die-before-ack-on K` applies (and durably records) the K-th new
entry, then os._exit(137) BEFORE XACK -- leaving it pending. On restart the
reclaim path picks it up and XACKs it without double-applying.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Dict, Optional

import store
from redis_client import Redis


def _extract(fields: Dict[str, Optional[str]]):
    """Return (event_id, account_id, symbol, qty_after, cash_delta) or None."""
    event_json = fields.get("event")
    if not event_json:
        return None
    try:
        root = json.loads(event_json)
    except (ValueError, TypeError):
        return None
    event_id = root.get("event_id")
    data = root.get("data") or {}
    if not event_id:
        return None
    return (
        event_id,
        data.get("account_id"),
        data.get("symbol"),
        float(data.get("position_after", 0.0)),
        float(data.get("cash_delta", 0.0)),
    )


def _handle(db: str, fields: Dict[str, Optional[str]]) -> bool:
    parsed = _extract(fields)
    if parsed is None:
        return False
    event_id, account_id, symbol, qty_after, cash_delta = parsed
    if store.already_processed(db, event_id):
        return False
    return store.apply(db, event_id, account_id, symbol, qty_after, cash_delta)


def main() -> int:
    p = argparse.ArgumentParser(description="Native killable idempotent consumer")
    p.add_argument("--db", required=True)
    p.add_argument("--stream", default="ledger.updates")
    p.add_argument("--group", default="cg:phase5-poc")
    p.add_argument("--consumer", default="phase5-poc-1")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=6379)
    p.add_argument("--min-idle-ms", type=int, default=0,
                   help="XAUTOCLAIM idle threshold (0 = reclaim immediately)")
    p.add_argument("--die-before-ack-on", type=int, default=0,
                   help="apply this new entry then exit(137) BEFORE XACK")
    p.add_argument("--max-idle-polls", type=int, default=3)
    args = p.parse_args()

    r = Redis(args.host, args.port)
    applied_new = 0
    reclaimed = 0
    idle_polls = 0
    try:
        # Ensure the consumer group exists (idempotent, MKSTREAM) BEFORE any
        # XAUTOCLAIM/XREADGROUP -- a fresh process (e.g. after a kill/restart)
        # would otherwise hit NOGROUP. Mirrors Phase5PocConsumer.ensureGroup().
        r.xgroup_create(args.stream, args.group, start_id="0", mkstream=True)
        while True:
            # 1) Reclaim stale pending entries left un-acked by a crash.
            _, claimed = r.xautoclaim(
                args.stream, args.group, args.consumer, args.min_idle_ms, "0"
            )
            for entry_id, fields in claimed:
                _handle(args.db, fields)  # dedupe makes a re-apply a no-op
                r.xack(args.stream, args.group, entry_id)
                reclaimed += 1

            # 2) Read one new entry (`>`).
            new_entries = r.xreadgroup(
                args.group, args.consumer, args.stream, count=1
            )
            if not new_entries:
                if r.xpending_count(args.stream, args.group) == 0:
                    idle_polls += 1
                    if idle_polls >= args.max_idle_polls:
                        break
                time.sleep(0.05)
                continue

            idle_polls = 0
            for entry_id, fields in new_entries:
                _handle(args.db, fields)
                applied_new += 1
                if (args.die_before_ack_on
                        and applied_new == args.die_before_ack_on):
                    # Effect durably recorded; DIE before XACK -> stays pending.
                    print(f"consumer: applied {applied_new} new entry(ies); "
                          f"DYING before XACK of {entry_id}", flush=True)
                    os._exit(137)
                r.xack(args.stream, args.group, entry_id)

        print(f"consumer: done (new-applied={applied_new}, reclaimed={reclaimed})",
              flush=True)
        return 0
    finally:
        r.close()


if __name__ == "__main__":
    sys.exit(main())
