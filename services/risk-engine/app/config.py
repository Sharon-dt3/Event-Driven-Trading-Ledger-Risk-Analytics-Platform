"""Configuration for the risk-engine consumer/publisher (Phase 6).

All values are environment-overridable so the same code runs in local dev,
CI, and deployment without edits. The consumer reads `ledger.updates` (and
`market.ticks` for latest prices) on the reserved group `cg:risk-engine`,
computes portfolio metrics, and publishes `RiskComputed.v1` to `risk.updates`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    """Immutable, env-derived runtime configuration."""

    redis_url: str = "redis://localhost:6379/0"

    # Streams (frozen contract names — see docs/contracts/streams/redis-streams.md).
    ledger_stream: str = "ledger.updates"
    ticks_stream: str = "market.ticks"
    risk_stream: str = "risk.updates"

    # The reserved production consumer group for the risk engine.
    group: str = "cg:risk-engine"
    consumer_name: str = "risk-engine-1"

    # Durable projection/dedupe store. Persisting this file is what makes the
    # consumer restart-safe (idempotent by envelope event_id across restarts).
    db_path: str = "risk_state.db"

    # Seed cash used as the portfolio-value baseline (POC-tier; matches the
    # end-to-end POC and ledger seed account).
    seed_cash: float = 10000.0

    # Read/reclaim tuning.
    batch_size: int = 100
    min_idle_ms: int = 30000
    poll_block_ms: int = 1000


def _get_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def from_env() -> Config:
    """Build a Config from environment variables (with safe defaults)."""
    return Config(
        redis_url=os.getenv("REDIS_URL", Config.redis_url),
        ledger_stream=os.getenv("LEDGER_STREAM", Config.ledger_stream),
        ticks_stream=os.getenv("TICKS_STREAM", Config.ticks_stream),
        risk_stream=os.getenv("RISK_STREAM", Config.risk_stream),
        group=os.getenv("RISK_CONSUMER_GROUP", Config.group),
        consumer_name=os.getenv("RISK_CONSUMER_NAME", Config.consumer_name),
        db_path=os.getenv("RISK_DB_PATH", Config.db_path),
        seed_cash=_get_float("RISK_SEED_CASH", Config.seed_cash),
        batch_size=_get_int("RISK_BATCH_SIZE", Config.batch_size),
        min_idle_ms=_get_int("RISK_MIN_IDLE_MS", Config.min_idle_ms),
        poll_block_ms=_get_int("RISK_POLL_BLOCK_MS", Config.poll_block_ms),
    )
