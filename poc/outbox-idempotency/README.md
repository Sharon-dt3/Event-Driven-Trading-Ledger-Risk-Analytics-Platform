# POC — Transactional Outbox + Idempotent Consumers + Double-Entry

> Status: **Proof of concept.** Runnable, dependency-light (Python stdlib + SQLite),
> with an in-process Redis-Streams simulator so the correctness properties can be
> proven deterministically (including injected crashes). It mirrors the production
> design frozen in `docs/contracts/`.

## 1. The gap we identified

The correctness core of TradePulse is the **ledger**. When a trade is posted it must
do two things that live in **two different systems**:

1. **Commit** the double-entry posting to PostgreSQL (journal entry + lines, updated
   cash/positions, audit row).
2. **Publish** a `LedgerUpdated.v1` event to Redis Streams so the risk engine (and
   dashboard) can react.

There is **no shared transaction across Postgres and Redis**. This is the classic
**dual-write problem**:

| Failure timing | Naive "commit then publish" | Naive "publish then commit" |
|----------------|-----------------------------|-----------------------------|
| Crash between the two | **Lost event** — DB has the trade, Redis never gets it → risk engine is permanently stale | **Phantom event** — consumers act on a trade that the DB rolled back |

On top of that, Redis Streams consumer groups deliver **at-least-once**, so even on
the happy path a consumer can see the **same event more than once** (redelivery after
a missed `XACK`, or a full **replay**). For a financial ledger, naive handling causes
**double-posting and balance drift** — an unacceptable correctness bug.

So the gap is precisely: **how do we guarantee that a committed trade is published
exactly-effectively-once, survives crashes/restarts/replays, and never corrupts ledger
state — without distributed transactions?**

## 2. The solution (in depth)

Four cooperating patterns:

### 2.1 Transactional Outbox
The event is **not** published inline. Instead, in the **same DB transaction** that
writes the trade, we also insert a row into an `outbox_events` table (`sent = 0`).
Because it is one local ACID transaction, the domain change and the "intent to
publish" commit **atomically**:

- Crash **before** commit → everything (trade **and** outbox row) rolls back → no
  phantom event.
- Crash **after** commit → the trade **and** the outbox row are both durable → the
  event is never lost.

### 2.2 Relay publisher
A separate loop reads `outbox_events WHERE sent = 0`, `XADD`s each to
`ledger.updates`, and marks it `sent = 1`. If the process dies mid-relay, on restart
it simply re-drains unsent rows. (This is why delivery is *at-least-once*, not
exactly-once, on the wire — which is fine because consumers are idempotent.)

### 2.3 Idempotent consumers
Every event carries a unique `event_id`. Consumers **dedupe by `event_id`** before
applying effects and only `XACK` **after** successful processing. Redelivery or replay
therefore has **no additional effect**.

### 2.4 Ledger idempotency (source-level)
The ledger enforces a **`UNIQUE` constraint on `source_event_id`** (== the client
`request_id`). A retried trade request short-circuits to the existing journal entry
instead of posting again — so client retries never double-post.

### 2.5 Double-entry invariant
Every posting writes balanced debit/credit lines; balances are **derived** from
journal lines rather than mutated blindly. The invariant `sum(debit) == sum(credit)`
is checkable at any time and must always hold.

## 3. What the POC proves (scenarios)

`run_scenarios.py` executes six scenarios with injected faults and asserts the
correctness property in each:

| # | Scenario | Property proven |
|---|----------|-----------------|
| S1 | Crash **after commit, before publish** | Event recovered by the relay → **no lost event** |
| S2 | Crash **before commit** | Trade + outbox roll back together → **no phantom event** |
| S3 | **Duplicate** stream delivery | Consumer applies **exactly once** (dedupe by `event_id`) |
| S4 | Consumer crash **before ACK** | Pending entry redelivered & applied once → **no loss** |
| S5 | **Retried `request_id`** | `UNIQUE source_event_id` → **no double-post** |
| S6 | **Full stream replay** (`SETID 0`) | Reprocessing leaves derived state unchanged |
| — | Global invariant | `sum(debit) == sum(credit)` holds after the workload |

## 4. How to run

```bash
cd Event-Driven-Trading-Ledger-Risk-Analytics-Platform/poc/outbox-idempotency
python run_scenarios.py
```

Expected tail: `ALL SCENARIOS PASSED`. Exit code is non-zero if any assertion fails.

No external services are required: the Redis Streams behavior (consumer groups,
pending-entries list, `XACK`, redelivery, `SETID` replay) is simulated in
`stream_bus.py` so the proof is deterministic and hermetic.

## 5. Mapping POC → production

| POC piece | Production equivalent |
|-----------|-----------------------|
| `stream_bus.StreamBus` | Redis Streams + consumer groups (`docs/contracts/streams/redis-streams.md`) |
| `ledger.Ledger` (SQLite) | ledger-core on PostgreSQL (`services/ledger-core`) |
| `outbox_events` table | `outbox_events` table + CDC/poller relay |
| `relay.relay_outbox` | Outbox publisher (poll or logical-replication CDC) |
| `consumer.RiskConsumer` | risk-engine consumer group `cg:risk-engine` (`services/risk-engine`) |
| `event_id` / `source_event_id` dedupe | Same fields in the frozen event envelope + `LedgerUpdated.v1` |

## 6. Limitations (intentional for a POC)

- SQLite stands in for PostgreSQL; the outbox/idempotency *pattern* is identical, but
  production must add a durable dedupe store (or `UNIQUE` processed-events table) for
  consumers rather than the in-memory `seen` set used here.
- The stream simulator is single-process and synchronous; it models delivery
  semantics, not throughput/latency.
- Relay is a simple poller; production may prefer CDC (logical replication) to avoid
  polling lag.
