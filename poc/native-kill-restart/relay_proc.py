#!/usr/bin/env python3
"""Killable outbox relay process (Phase 5 Task 2, native).

Drains unsent `outbox_events` oldest-first and, per row, XADDs to the stream
and only THEN marks it `sent=1` (publish-then-mark-sent), exactly like
`OutboxRelay`. If it dies between XADD and mark-sent, that row stays unsent and
is re-published on the next run -> an at-least-once duplicate on the wire, which
the consumer dedupes.

The orchestrator drives two runs:
  1. `--die-after-publish K`: XADD the K-th row, then os._exit(137) BEFORE
     marking it sent (simulating a hard kill at the exact publish/mark gap).
  2. a plain run that re-drains the remaining unsent rows to completion.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import store
from redis_client import Redis


def main() -> int:
    p = argparse.ArgumentParser(description="Native killable outbox relay")
    p.add_argument("--db", required=True)
    p.add_argument("--stream", default="ledger.updates")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=6379)
    p.add_argument("--sleep-ms", type=int, default=0,
                   help="delay between rows (lets a real SIGKILL land mid-drain)")
    p.add_argument("--die-after-publish", type=int, default=0,
                   help="XADD this row then exit(137) BEFORE marking it sent")
    args = p.parse_args()

    r = Redis(args.host, args.port)
    published = 0
    try:
        for event_id, event_type, payload in store.unsent_outbox(args.db):
            fields = store.build_stream_fields(event_type, payload)
            r.xadd(args.stream, fields)
            published += 1
            if args.die_after_publish and published == args.die_after_publish:
                # Hard "crash" AFTER publish, BEFORE mark-sent: the row remains
                # sent=0 and will be re-published (re-drained) on restart.
                print(f"relay: published {published} row(s); DYING before "
                      f"marking '{event_id}' sent", flush=True)
                os._exit(137)
            store.mark_sent(args.db, event_id)
            if args.sleep_ms:
                time.sleep(args.sleep_ms / 1000.0)
        print(f"relay: drained cleanly, published {published} row(s)", flush=True)
        return 0
    finally:
        r.close()


if __name__ == "__main__":
    sys.exit(main())
