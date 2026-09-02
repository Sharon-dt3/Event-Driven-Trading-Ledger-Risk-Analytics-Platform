"""Risk-engine stream worker (Redis I/O) — Phase 6.

Wires the Redis Streams wire path to the Redis-free `RiskConsumer` core:

* ensures the reserved `cg:risk-engine` group on both `market.ticks` and
  `ledger.updates` (MKSTREAM, idempotent);
* each cycle: reclaim stale pending `ledger.updates` entries via XAUTOCLAIM
  (dedupe makes an already-applied reclaim a no-op), refresh the latest-price
  cache from `market.ticks`, then drain new `ledger.updates` entries — for each,
  compute metrics and publish `RiskComputed.v1` to `risk.updates`, then XACK.

Run:  python -m app.worker            (loops until interrupted)
      python -m app.worker --once     (one drain cycle, for scripted checks)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from typing import List, Tuple

import redis

from .config import Config, from_env
from .consumer import RiskConsumer
from .logging_config import configure_logging
from .store import RiskStore

logger = logging.getLogger("risk-engine.worker")

Entry = Tuple[str, dict]


def _decode_entries(reply) -> List[Tuple[str, dict]]:
    out: List[Tuple[str, dict]] = []
    if not reply:
        return out
    for _stream, entries in reply:
        for entry_id, fields in entries or []:
            out.append((entry_id, fields))
    return out


def _parse_event(fields: dict):
    raw = fields.get("event")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


class RiskWorker:
    def __init__(self, r: "redis.Redis", consumer: RiskConsumer, config: Config) -> None:
        self.r = r
        self.consumer = consumer
        self.cfg = config
        # Monotonic timestamp of the last 2B throttle recompute (None = never).
        self._last_recompute = None

    def ensure_groups(self) -> None:
        for stream in (self.cfg.ticks_stream, self.cfg.ledger_stream):
            try:
                self.r.xgroup_create(stream, self.cfg.group, id="0", mkstream=True)
            except redis.exceptions.ResponseError as ex:
                if "BUSYGROUP" not in str(ex):
                    raise

    def refresh_prices(self) -> int:
        reply = self.r.xreadgroup(
            self.cfg.group, self.cfg.consumer_name,
            {self.cfg.ticks_stream: ">"}, count=self.cfg.batch_size)
        n = 0
        for entry_id, fields in _decode_entries(reply):
            env = _parse_event(fields)
            if env is not None:
                self.consumer.process_tick_envelope(env)
            self.r.xack(self.cfg.ticks_stream, self.cfg.group, entry_id)
            n += 1
        return n

    def reclaim_ledger(self) -> int:
        cursor = "0-0"
        reclaimed = 0
        # Bounded single pass; a running worker revisits next cycle.
        result = self.r.xautoclaim(
            self.cfg.ledger_stream, self.cfg.group, self.cfg.consumer_name,
            min_idle_time=self.cfg.min_idle_ms, start_id=cursor,
            count=self.cfg.batch_size)
        entries = result[1] if result and len(result) > 1 else []
        for entry_id, fields in entries or []:
            env = _parse_event(fields)
            if env is not None:
                risk_env = self.consumer.process_ledger_envelope(env)
                if risk_env is not None:
                    self._publish(risk_env)
            self.r.xack(self.cfg.ledger_stream, self.cfg.group, entry_id)
            reclaimed += 1
        return reclaimed

    def drain_ledger(self) -> int:
        reply = self.r.xreadgroup(
            self.cfg.group, self.cfg.consumer_name,
            {self.cfg.ledger_stream: ">"}, count=self.cfg.batch_size)
        published = 0
        for entry_id, fields in _decode_entries(reply):
            env = _parse_event(fields)
            if env is not None:
                risk_env = self.consumer.process_ledger_envelope(env)
                if risk_env is not None:
                    self._publish(risk_env)
                    published += 1
            self.r.xack(self.cfg.ledger_stream, self.cfg.group, entry_id)
        return published

    def _publish(self, risk_env: dict) -> None:
        self.r.xadd(self.cfg.risk_stream, RiskConsumer.stream_fields(risk_env))
        logger.info(
            "risk_computed_published",
            extra={"extra_fields": {
                "account_id": risk_env["data"]["account_id"],
                "portfolio_value": risk_env["data"]["portfolio_value"],
                "pnl": risk_env["data"]["pnl"],
                "stream": self.cfg.risk_stream,
            }},
        )

    def cycle(self) -> int:
        self.reclaim_ledger()
        self.refresh_prices()
        return self.drain_ledger()

    def maybe_recompute(self, now: float = None) -> int:
        """2B throttle: at most one recompute per ``recompute_interval_ms``.

        Coalesces bursts of ticks into a single interval-spaced recompute (not
        one publish per tick) and fires from price movement alone (no new trade
        required), because PV changes as marks change. ``now`` is injectable
        (monotonic seconds) so the cadence is deterministic under test.
        """
        current = time.monotonic() if now is None else now
        if (self._last_recompute is not None
                and (current - self._last_recompute) * 1000.0
                < self.cfg.recompute_interval_ms):
            return 0
        self._last_recompute = current
        published = 0
        for account_id in self.consumer.store.accounts():
            risk_env = self.consumer.recompute_account(account_id)
            if risk_env is not None:
                self._publish(risk_env)
                published += 1
        return published


def build_worker(config: Config) -> RiskWorker:
    r = redis.from_url(config.redis_url, decode_responses=True)
    store = RiskStore(config.db_path)
    consumer = RiskConsumer(store, config)
    worker = RiskWorker(r, consumer, config)
    worker.ensure_groups()
    return worker


def main(argv=None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description="Risk-engine stream worker")
    parser.add_argument("--once", action="store_true",
                        help="run a single drain cycle and exit")
    parser.add_argument("--idle-exit-cycles", type=int, default=0,
                        help="exit after N consecutive empty cycles (0 = never)")
    args = parser.parse_args(argv)

    cfg = from_env()
    worker = build_worker(cfg)
    logger.info("risk_worker_started", extra={"extra_fields": {
        "group": cfg.group, "ledger_stream": cfg.ledger_stream,
        "risk_stream": cfg.risk_stream, "db_path": cfg.db_path}})

    if args.once:
        published = worker.cycle()
        published += worker.maybe_recompute()
        logger.info("risk_worker_once_done",
                    extra={"extra_fields": {"published": published}})
        return 0

    empty = 0
    try:
        while True:
            published = worker.cycle()
            published += worker.maybe_recompute()
            if published == 0:
                empty += 1
                if args.idle_exit_cycles and empty >= args.idle_exit_cycles:
                    return 0
                time.sleep(cfg.poll_block_ms / 1000.0)
            else:
                empty = 0
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
