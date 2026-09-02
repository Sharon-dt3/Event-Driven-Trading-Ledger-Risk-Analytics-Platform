#!/usr/bin/env python3
"""Phase 5 Task 5 -- native kill/restart proof against a REAL local redis-server.

This is the Phase 5 "done when": it exercises the Task 2 outbox relay and the
Task 3 idempotent consumer end-to-end, under two real OS-process kills, and
proves the reliability guarantee holds:

  post trades -> drain -> KILL relay mid-drain + restart
              -> KILL consumer before XACK + restart
  => applied effects == distinct event_ids
  => consumer projection (cash + positions) == single-delivery baseline
  => XPENDING == 0 (every entry ultimately acked)

Unlike the in-process `outbox-idempotency` POC (which simulates Redis and
in-memory dedupe), this drives the ACTUAL Redis Streams wire protocol on
localhost:6379 and kills separate relay/consumer subprocesses with SIGKILL, so
the dedupe MUST be restart-safe (persisted in SQLite) -- which is exactly the
property a real risk-engine consumer needs and the throwaway `cg:phase5-poc`
Java bean intentionally does not have.

Run:
    cd Event-Driven-Trading-Ledger-Risk-Analytics-Platform/poc/native-kill-restart
    python run_proof.py

Requirements: a `redis-server` binary on PATH (the script starts its own
instance on an ephemeral port and tears it down), or an already-running Redis
reachable via --host/--port with --no-spawn. Uses the `redis-py` client for
Redis access (already available in this environment); everything else is stdlib.

Exit code is non-zero if any assertion fails.
"""
from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time

import seed
import store
from redis_client import Redis, RedisError

HERE = os.path.dirname(os.path.abspath(__file__))
STREAM = "ledger.updates"
GROUP = "cg:phase5-poc"
CONSUMER = "phase5-poc-1"


def log(msg: str) -> None:
    print(msg, flush=True)


def sep(title: str) -> None:
    log("\n" + "=" * 72 + f"\n{title}\n" + "=" * 72)


# --- local redis lifecycle ---------------------------------------------
def wait_for_redis(host: str, port: int, timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    last: Exception | None = None
    while time.time() < deadline:
        try:
            r = Redis(host, port, timeout=1.0)
            if r.ping().upper() == "PONG":
                r.close()
                return
            r.close()
        except (OSError, RedisError) as ex:
            last = ex
            time.sleep(0.1)
    raise RuntimeError(f"redis at {host}:{port} not reachable: {last}")


def start_redis(port: int, workdir: str) -> subprocess.Popen:
    binary = shutil.which("redis-server")
    if not binary:
        raise FileNotFoundError(
            "redis-server not found on PATH. Install redis, or point the proof "
            "at a running instance with --no-spawn --host <h> --port <p>."
        )
    proc = subprocess.Popen(
        [binary, "--port", str(port), "--save", "", "--appendonly", "no",
         "--dir", workdir],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    wait_for_redis("127.0.0.1", port)
    return proc


def run_child(script: str, extra_args: list[str], env: dict) -> int:
    """Run a proof subprocess; return its exit code (137 == self-kill point)."""
    cmd = [sys.executable, os.path.join(HERE, script)] + extra_args
    proc = subprocess.Popen(cmd, cwd=HERE, env=env)
    return proc.wait()


# --- the proof ----------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="Native kill/restart proof")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=0,
                    help="Redis port (0 = pick an ephemeral port when spawning)")
    ap.add_argument("--no-spawn", action="store_true",
                    help="use an already-running Redis instead of starting one")
    args = ap.parse_args()

    child_env = dict(os.environ)
    child_env["PYTHONPATH"] = HERE + os.pathsep + child_env.get("PYTHONPATH", "")

    workdir = tempfile.mkdtemp(prefix="tp-phase5-task5-")
    db_path = os.path.join(workdir, "proof.db")

    redis_proc: subprocess.Popen | None = None
    port = args.port
    try:
        # 0) Bring up a real Redis (own instance unless --no-spawn).
        sep("SETUP: local redis-server + seeded outbox")
        if args.no_spawn:
            if port == 0:
                port = 6379
            wait_for_redis(args.host, port)
            log(f"  using existing redis at {args.host}:{port}")
        else:
            if port == 0:
                # Grab a free port from the OS.
                import socket
                s = socket.socket()
                s.bind(("127.0.0.1", 0))
                port = s.getsockname()[1]
                s.close()
            redis_proc = start_redis(port, workdir)
            log(f"  started redis-server on 127.0.0.1:{port} (dir={workdir})")

        host = args.host

        # Clean slate for this stream/group on the target Redis.
        admin = Redis(host, port)
        admin.xgroup_destroy(STREAM, GROUP)
        admin.delete(STREAM)
        admin.close()

        # Seed the outbox + projection and compute the single-delivery baseline.
        store.init(db_path)
        events = seed.generate()
        store.seed_outbox(db_path, events)
        store.init_projection(db_path, seed.ACCOUNT_ID, seed.SEED_CASH)
        base_cash, base_positions = seed.baseline(events)
        distinct_event_ids = {e["event_id"] for e in events}
        log(f"  seeded {len(events)} outbox rows; distinct event_ids="
            f"{len(distinct_event_ids)}")
        log(f"  single-delivery baseline: cash={base_cash} positions={base_positions}")

        common = ["--db", db_path, "--host", host, "--port", str(port),
                  "--stream", STREAM]

        # 1) KILL POINT #1 -- relay dies mid-drain (after XADD, before mark-sent).
        sep("KILL POINT 1: relay publishes a row, then is killed before mark-sent")
        die_on = 3  # publish rows 1..3, die before marking row 3 sent
        rc = run_child("relay_proc.py", common + ["--die-after-publish", str(die_on)],
                       child_env)
        log(f"  relay run #1 exit={rc} (137 = self-kill at publish/mark gap)")
        assert rc == 137, f"relay should have self-killed at the gap, got rc={rc}"
        r = Redis(host, port)
        len_after_kill = r.xlen(STREAM)
        r.close()
        unsent_after_kill = store.unsent_count(db_path)
        log(f"  stream_len={len_after_kill}, unsent_rows={unsent_after_kill} "
            f"(row {die_on} published but NOT marked -> still unsent)")
        assert len_after_kill == die_on, "expected rows 1..die_on on the stream"
        assert unsent_after_kill == len(events) - (die_on - 1), \
            "the un-marked published row must remain unsent (re-publishable)"

        # Restart the relay: it re-drains unsent rows (re-publishing row 3 -> dup).
        rc = run_child("relay_proc.py", common, child_env)
        log(f"  relay run #2 (restart) exit={rc}")
        assert rc == 0, "relay restart should drain cleanly"
        r = Redis(host, port)
        len_final = r.xlen(STREAM)
        r.close()
        log(f"  stream_len={len_final} (== {len(events)} distinct + "
            f"{len_final - len(events)} at-least-once duplicate)")
        assert len_final == len(events) + 1, \
            "restart must re-publish exactly the un-marked row (one duplicate)"
        assert store.unsent_count(db_path) == 0, "all outbox rows must be sent"

        # 2) KILL POINT #2 -- consumer dies before XACK; restart reclaims.
        sep("KILL POINT 2: consumer applies an entry, then is killed before XACK")
        die_on_c = 2  # apply 2 new entries, die before XACK of the 2nd
        rc = run_child(
            "consumer_proc.py",
            common + ["--group", GROUP, "--consumer", CONSUMER,
                      "--min-idle-ms", "0", "--die-before-ack-on", str(die_on_c)],
            child_env,
        )
        log(f"  consumer run #1 exit={rc} (137 = self-kill before XACK)")
        assert rc == 137, f"consumer should have self-killed before XACK, got rc={rc}"
        r = Redis(host, port)
        pending_after_kill = r.xpending_count(STREAM, GROUP)
        r.close()
        log(f"  XPENDING={pending_after_kill} (the un-acked applied entry is pending)")
        assert pending_after_kill >= 1, "the un-acked entry must be pending after crash"

        # Restart the consumer: reclaim the pending entry (dedupe => no double-apply)
        # and drain the rest.
        rc = run_child(
            "consumer_proc.py",
            common + ["--group", GROUP, "--consumer", CONSUMER, "--min-idle-ms", "0"],
            child_env,
        )
        log(f"  consumer run #2 (restart) exit={rc}")
        assert rc == 0, "consumer restart should complete cleanly"

        # 3) ASSERT the Phase 5 done-when.
        sep("ASSERT: applied effects == distinct event_ids; projection == baseline")
        r = Redis(host, port)
        pending_final = r.xpending_count(STREAM, GROUP)
        r.close()
        processed = store.processed_ids(db_path)
        proj_cash, proj_positions = store.projection(db_path, seed.ACCOUNT_ID)

        log(f"  distinct event_ids           = {len(distinct_event_ids)}")
        log(f"  applied (processed_events)   = {len(processed)}")
        log(f"  XPENDING (final)             = {pending_final}")
        log(f"  projection cash              = {proj_cash} (baseline {base_cash})")
        log(f"  projection positions         = {proj_positions}")
        log(f"  baseline   positions         = {base_positions}")

        assert set(processed) == distinct_event_ids, \
            "applied effects must equal the set of distinct event_ids"
        assert len(processed) == len(distinct_event_ids), \
            "no event_id may be applied more than once"
        assert pending_final == 0, "every stream entry must ultimately be XACKed"
        assert abs(proj_cash - base_cash) < 1e-9, \
            f"cash drift: got {proj_cash}, baseline {base_cash}"
        assert proj_positions == base_positions, \
            f"position drift: got {proj_positions}, baseline {base_positions}"

        sep("PHASE 5 TASK 5 PROOF PASSED")
        log("  Survived BOTH kill points (relay mid-drain, consumer before XACK).")
        log("  Applied-exactly-once across a real duplicate + XAUTOCLAIM reclaim.")
        log("  Derived balances/positions match the single-delivery baseline.")
        return 0

    except AssertionError as ex:
        log(f"\nPROOF FAILED: {ex}")
        return 1
    except (RuntimeError, FileNotFoundError, RedisError, OSError) as ex:
        log(f"\nPROOF ERROR: {ex}")
        return 2
    finally:
        if redis_proc is not None:
            redis_proc.send_signal(signal.SIGTERM)
            try:
                redis_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                redis_proc.kill()
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
