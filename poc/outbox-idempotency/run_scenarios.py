"""Run the POC scenarios that prove the outbox + idempotency + double-entry design.

Each scenario injects a fault (crash, duplicate, replay, retry) and asserts the
correctness property. Exit code is non-zero if any assertion fails.

Run:
    python run_scenarios.py
"""
from __future__ import annotations

import sys

from consumer import RiskConsumer
from ledger import CrashInjected, Ledger
from relay import relay_outbox
from stream_bus import StreamBus

STREAM = "ledger.updates"
GROUP = "cg:risk-engine"


def sep(title: str) -> None:
    print("\n" + "=" * 68 + f"\n{title}\n" + "=" * 68)


def req(rid: str, side: str = "BUY", q: float = 10, p: float = 100.0) -> dict:
    return {
        "request_id": rid,
        "account_id": "acct_123",
        "symbol": "AAPL",
        "side": side,
        "quantity": q,
        "price": p,
        "correlation_id": "corr-1",
    }


def s1_crash_after_commit() -> None:
    sep("S1: crash after COMMIT, before publish -> outbox relay recovers event")
    L, B = Ledger(), StreamBus()
    try:
        L.post_trade(req("r1"), crash_point="after_commit_before_publish")
    except CrashInjected as e:
        print("  ! crash:", e)
    print("  je_count=", L.je_count(), "cash=", L.cash(), "stream_len=", B.stream_len(STREAM))
    published = relay_outbox(L, B)
    print("  relayed=", published, "stream_len_now=", B.stream_len(STREAM))
    assert B.stream_len(STREAM) == 1, "event must be recovered from outbox"
    print("  PASS: no lost event")


def s2_crash_before_commit() -> None:
    sep("S2: crash before COMMIT -> atomic rollback, no phantom event")
    L, B = Ledger(), StreamBus()
    try:
        L.post_trade(req("r2"), crash_point="before_commit")
    except CrashInjected as e:
        print("  ! crash:", e)
    print("  je_count=", L.je_count(), "unsent_outbox=", len(L.unsent_outbox()))
    relay_outbox(L, B)
    assert L.je_count() == 0 and B.stream_len(STREAM) == 0
    print("  PASS: no phantom event")


def s3_duplicate_delivery() -> None:
    sep("S3: duplicate stream delivery -> idempotent consumer dedupes")
    L, B = Ledger(), StreamBus()
    L.post_trade(req("r3"))
    relay_outbox(L, B, inject_dup=True)
    C = RiskConsumer(B)
    C.poll()
    print("  stream_len=", B.stream_len(STREAM), "applied=", C.applied, "skipped=", C.skipped)
    assert C.applied == 1 and C.skipped == 1
    print("  PASS: applied exactly once")


def s4_consumer_crash_before_ack() -> None:
    sep("S4: consumer crash before ACK -> PEL redelivery")
    L, B = Ledger(), StreamBus()
    L.post_trade(req("r4"))
    relay_outbox(L, B)
    C = RiskConsumer(B)
    print("  poll->", C.poll(crash_before_ack=True), "pending=", len(B.xpending(STREAM, GROUP)))
    C.recover()
    print("  after recover applied=", C.applied, "pending=", len(B.xpending(STREAM, GROUP)))
    assert C.applied == 1 and len(B.xpending(STREAM, GROUP)) == 0
    print("  PASS: redelivered & applied once")


def s5_retried_request() -> None:
    sep("S5: retried request_id -> ledger idempotency, no double-post")
    L = Ledger()
    L.post_trade(req("r5"))
    cash1, pos1 = L.cash(), L.position("acct_123", "AAPL")
    b = L.post_trade(req("r5"))
    print("  retry idempotent_replay=", b.get("idempotent_replay"), "je_count=", L.je_count())
    assert L.je_count() == 1 and L.cash() == cash1 and L.position("acct_123", "AAPL") == pos1
    print("  PASS: no double-post")


def s6_replay() -> None:
    sep("S6: full stream replay (SETID 0) -> derived state unchanged")
    L, B = Ledger(), StreamBus()
    for i, rid in enumerate(["r6a", "r6b"]):
        L.post_trade(req(rid, q=5 + i))
    relay_outbox(L, B)
    C = RiskConsumer(B)
    C.poll()
    view_before = dict(C.position_view)
    B.setid(STREAM, GROUP, 0)  # replay from the beginning
    C.poll()
    print("  view_before=", view_before, "view_after=", C.position_view, "skipped=", C.skipped)
    assert C.position_view == view_before, "replay must not change derived state"
    print("  PASS: replay idempotent")
    # Global invariant on the mixed workload.
    d, c = L.assert_double_entry()
    print("  GLOBAL double-entry: debits=", d, "credits=", c, "-> balanced")


def main() -> int:
    try:
        s1_crash_after_commit()
        s2_crash_before_commit()
        s3_duplicate_delivery()
        s4_consumer_crash_before_ack()
        s5_retried_request()
        s6_replay()
    except AssertionError as e:
        print("\nSCENARIO FAILED:", e)
        return 1
    print("\nALL SCENARIOS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
