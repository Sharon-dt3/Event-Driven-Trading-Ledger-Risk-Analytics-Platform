#!/usr/bin/env python3
"""Phase 6 thin-slice LIVE wire proof (risk-engine) against a real redis-server.

This is the "watched it work" bar for the risk engine's first slice. It:

1. starts its own `redis-server` on an ephemeral port (torn down at the end);
2. publishes a real `LedgerUpdated.v1` envelope to `ledger.updates`
   (the same shape ledger-core's outbox emits);
3. runs the ACTUAL shipped worker (`app.worker.RiskWorker.cycle()`) against it;
4. reads the published `RiskComputed.v1` back off `risk.updates` via XREVRANGE
   and asserts portfolio_value / pnl are correct and the three history metrics
   are present-but-zero;
5. validates the emitted envelope against the FROZEN `RiskComputed.v1` JSON
   Schema (not just "looks contract-shaped");
6. feeds the SAME `LedgerUpdated` again and proves the shipped worker dedupes
   on the wire: exactly one applied effect in the durable projection and exactly
   one `RiskComputed` on the stream.

Run:  python utils/live_wire_proof.py     (from services/risk-engine)

Requires a `redis-server` binary on PATH. Python: redis, jsonschema, referencing.
Exit code is non-zero on any assertion failure.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import redis

# --- make app.* and the repo contract validator importable ---------------
SERVICE_DIR = Path(__file__).resolve().parents[1]      # services/risk-engine
REPO_ROOT = SERVICE_DIR.parents[1]                     # repo root
sys.path.insert(0, str(SERVICE_DIR))
sys.path.insert(0, str(REPO_ROOT / "utils"))

from app.config import Config              # noqa: E402
from app.consumer import RiskConsumer      # noqa: E402
from app.store import RiskStore            # noqa: E402
from app.worker import RiskWorker          # noqa: E402
from jsonschema import Draft202012Validator  # noqa: E402
import validate_contracts                  # noqa: E402  (Phase 0 validator)

STREAM_LEDGER = "ledger.updates"
STREAM_RISK = "risk.updates"
STREAM_TICKS = "market.ticks"


def log(m: str) -> None:
    print(m, flush=True)


def sep(t: str) -> None:
    log("\n" + "=" * 72 + f"\n{t}\n" + "=" * 72)


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def wait_redis(r: "redis.Redis", timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if r.ping():
                return
        except redis.exceptions.RedisError:
            time.sleep(0.1)
    raise RuntimeError("redis did not come up")


def ledger_envelope(event_id: str, correlation_id: str, *, symbol="AAPL",
                    side="BUY", qty=10, price=100.0, cash_delta=-1000.0,
                    position_after=10, account="acct_123") -> dict:
    return {
        "event_id": event_id,
        "event_type": "LedgerUpdated",
        "schema_version": "1",
        "correlation_id": correlation_id,
        "produced_at": "2026-09-01T12:00:00.500Z",
        "producer": "ledger-core",
        "data": {
            "journal_entry_id": "je_1001",
            "source_event_id": str(uuid.uuid4()),
            "account_id": account, "symbol": symbol, "side": side,
            "quantity": qty, "price": price, "cash_delta": cash_delta,
            "position_after": position_after,
            "posted_at": "2026-09-01T12:00:00.500Z",
        },
    }


def publish_ledger(r: "redis.Redis", env: dict) -> None:
    r.xadd(STREAM_LEDGER, {
        "event_type": env["event_type"],
        "schema_version": env["schema_version"],
        "event": json.dumps(env),
    })


def read_latest_risk(r: "redis.Redis") -> dict | None:
    entries = r.xrevrange(STREAM_RISK, "+", "-", count=1)
    if not entries:
        return None
    _id, fields = entries[0]
    return json.loads(fields["event"])


def validate_against_schema(env: dict) -> list[str]:
    registry = validate_contracts.build_registry()
    schema = validate_contracts.load_json(
        REPO_ROOT / "docs/contracts/events/risk_computed.v1.schema.json")
    validator = Draft202012Validator(schema, registry=registry)
    return [f"{'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}"
            for e in validator.iter_errors(env)]


def main() -> int:
    binary = shutil.which("redis-server")
    if not binary:
        log("redis-server not found on PATH")
        return 2

    workdir = tempfile.mkdtemp(prefix="risk-wire-")
    port = free_port()
    redis_proc = subprocess.Popen(
        [binary, "--port", str(port), "--save", "", "--appendonly", "no",
         "--dir", workdir],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        url = f"redis://127.0.0.1:{port}/0"
        r = redis.from_url(url, decode_responses=True)
        wait_redis(r)

        # Build the ACTUAL shipped worker against this Redis + a durable DB.
        db_path = os.path.join(workdir, "risk_state.db")
        cfg = Config(redis_url=url, db_path=db_path)
        store = RiskStore(db_path)
        worker = RiskWorker(r, RiskConsumer(store, cfg), cfg)
        worker.ensure_groups()

        # 1) Post a real LedgerUpdated, run the worker, read RiskComputed back.
        sep("LIVE: LedgerUpdated -> worker -> RiskComputed on risk.updates")
        cid = str(uuid.uuid4())
        eid = str(uuid.uuid4())
        # Marked at trade price (no tick) -> PV == seed (10000), PnL == 0.
        publish_ledger(r, ledger_envelope(eid, cid))
        published = worker.cycle()
        log(f"  worker.cycle() published={published}")
        assert published == 1, f"expected 1 RiskComputed published, got {published}"

        risk = read_latest_risk(r)
        assert risk is not None, "no RiskComputed on risk.updates"
        log("  XREVRANGE risk.updates + - COUNT 1:")
        log("  " + json.dumps(risk, indent=2).replace("\n", "\n  "))
        d = risk["data"]
        assert d["portfolio_value"] == 10000.0, d["portfolio_value"]
        assert d["pnl"] == 0.0, d["pnl"]
        assert d["volatility"] == 0.0 and d["var"] == 0.0 and d["sharpe"] == 0.0
        assert risk["correlation_id"] == cid, "correlation_id must propagate"

        # 2) Validate the REAL emitted bytes against the frozen schema.
        sep("LIVE: validate emitted envelope against frozen RiskComputed.v1 schema")
        errors = validate_against_schema(risk)
        if errors:
            log("  SCHEMA ERRORS:")
            for e in errors:
                log(f"    - {e}")
            raise AssertionError("emitted RiskComputed.v1 failed schema validation")
        log("  PASS: emitted envelope validates against the frozen schema")

        # 3) Duplicate delivery -> the shipped worker dedupes on the wire.
        sep("LIVE: duplicate LedgerUpdated -> exactly one effect, one publish")
        risk_len_before = r.xlen(STREAM_RISK)
        applied_before = store.applied_count()
        publish_ledger(r, ledger_envelope(eid, cid))  # SAME event_id
        published2 = worker.cycle()
        risk_len_after = r.xlen(STREAM_RISK)
        applied_after = store.applied_count()
        log(f"  duplicate: worker published={published2}, "
            f"risk.updates {risk_len_before}->{risk_len_after}, "
            f"applied {applied_before}->{applied_after}")
        assert published2 == 0, "duplicate must not publish a second RiskComputed"
        assert risk_len_after == risk_len_before, "risk.updates must not grow"
        assert applied_after == applied_before == 1, "exactly one durable effect"

        # 4) Throttled tick-driven recompute (2B) makes volatility live.
        sep("LIVE: throttle (2B) -> volatility/VaR/Sharpe live on the wire")
        # Account already holds 10 AAPL @ trade price 100, cash 9000 (scenario 1).
        # Marks drive PV: 100->10000, 110->10100, 99.9->9999
        #   PV returns [0.01, -0.01] -> volatility 0.01 (pstdev),
        #   var = 1.65 * 0.01 * 9999 = 164.98 (parametric), sharpe = 0 (mean 0).
        marks = [100.0, 110.0, 99.9]
        for i, mk in enumerate(marks):
            r.xadd(STREAM_TICKS, {
                "event_type": "TickReceived",
                "schema_version": "1",
                "event": json.dumps({
                    "event_id": str(uuid.uuid4()), "event_type": "TickReceived",
                    "schema_version": "1", "correlation_id": cid,
                    "produced_at": "2026-09-01T12:00:00.500Z",
                    "producer": "market-data",
                    "data": {"symbol": "AAPL", "price": mk, "source": "sim",
                             "tick_time": "2026-09-01T12:00:00.500Z"}}),
            })
            worker.refresh_prices()
            worker.maybe_recompute(now=1000.0 + i * 2.0)  # 2s apart > 1s interval
        vrisk = read_latest_risk(r)
        assert vrisk is not None, "no RiskComputed after throttle"
        vd = vrisk["data"]
        log("  latest RiskComputed.data after throttle:")
        log("  " + json.dumps(vd, indent=2).replace("\n", "\n  "))
        assert vd["portfolio_value"] == 9999.0, vd["portfolio_value"]
        assert vd["pnl"] == -1.0, vd["pnl"]
        assert vd["volatility"] == 0.01, vd["volatility"]
        assert vd["var"] == 164.98, vd["var"]          # parametric 1.65*vol*pv
        assert vd["sharpe"] == 0.0, vd["sharpe"]
        errs2 = validate_against_schema(vrisk)
        if errs2:
            for e in errs2:
                log(f"    - {e}")
            raise AssertionError("throttle RiskComputed failed schema validation")
        log("  PASS: volatility 0.01 live, VaR 164.98 parametric, schema-valid")

        sep("PHASE 6 THIN-SLICE LIVE WIRE PROOF PASSED")
        log("  Real ledger event -> real metric -> RiskComputed on the wire.")
        log("  Emitted envelope validated against the frozen schema.")
        log("  Shipped worker deduped a duplicate live: one effect, one publish.")
        return 0
    except AssertionError as ex:
        log(f"\nWIRE PROOF FAILED: {ex}")
        return 1
    finally:
        redis_proc.send_signal(signal.SIGTERM)
        try:
            redis_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            redis_proc.kill()
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
