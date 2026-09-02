# POC — Phase 5 Task 5: Native kill/restart proof

> Status: **Runnable proof against a real `redis-server`.** This is the Phase 5
> **"done when"**: it exercises the Task 2 outbox relay and the Task 3 idempotent
> consumer end-to-end, under two genuine OS-process kills, and asserts the
> reliability guarantee holds. Redis access goes through the battle-tested
> **`redis-py`** client (already available in this environment) — deliberately
> *not* a hand-rolled RESP client, so the proof of correctness never rests on
> fragile protocol parsing (the exact class of bug hit in Task 3's XAUTOCLAIM
> reclaim). Everything else is Python standard library.

## What it proves

```
post trades → drain → KILL relay mid-drain + restart
                    → KILL consumer before XACK + restart
  ⇒ applied effects == distinct event_ids
  ⇒ consumer projection (cash + positions) == single-delivery baseline
  ⇒ XPENDING == 0   (every entry ultimately acked)
```

Unlike the in-process [`../outbox-idempotency`](../outbox-idempotency/) POC — which
*simulates* Redis (`stream_bus.py`) and dedupes in memory — this proof drives the
**actual Redis Streams wire protocol** on `localhost:6379` and kills **separate
relay/consumer subprocesses** with a hard `exit(137)`. Because the process really
dies, the consumer's dedupe must be **restart-safe**, so it is persisted in SQLite
(`processed_events`). That is exactly what the real `cg:risk-engine` consumer will
do, and it is the property the throwaway in-memory `cg:phase5-poc` Java bean
(`Phase5PocConsumer`) intentionally does **not** have.

## The two kill points

| # | Kill point | Mechanism | Property proven |
|---|------------|-----------|-----------------|
| 1 | **Relay dies mid-drain** — after `XADD` of a row, **before** `mark-sent` | `relay_proc.py --die-after-publish K` self-`exit(137)` at the publish/mark gap | The un-marked row stays `sent=0` and is **re-published on restart** → an at-least-once duplicate on the stream. Matches `OutboxRelay` publish-then-mark-sent. |
| 2 | **Consumer dies before ACK** — after applying+persisting an entry, **before** `XACK` | `consumer_proc.py --die-before-ack-on K` self-`exit(137)` before `XACK` | The entry stays in the group PEL; on restart `XAUTOCLAIM` reclaims it and dedupe (persisted `event_id`) makes the re-apply a **no-op**. Matches `Phase5PocConsumer` reclaim path. |

After both kills + restarts, the consumer projection must equal the **single-delivery
baseline** (the state of a perfect, fault-free run) despite one duplicate delivery
and one reclaimed pending entry.

### Scope: what this proves — and, precisely, what it does not

This proof validates the Phase 5 **reliability *design*** — that the outbox
relay + idempotent-consumer pattern loses nothing and double-applies nothing
across real process crashes. It does **not** prove that the shipped Java
`Phase5PocConsumer` is restart-safe, because a **different consumer** does the
surviving here:

- **This proof's consumer** (`consumer_proc.py`) dedupes by `event_id` in a
  **durable SQLite table** (`processed_events`), written in the *same
  transaction* as the projection. That is why it survives a full process
  restart: a fresh process reloads what was already applied and treats a
  reclaimed entry as a no-op. This mirrors what the real `cg:risk-engine`
  consumer must do.
- **The committed Java `Phase5PocConsumer`** (group `cg:phase5-poc`) keeps its
  dedupe set **in memory**, so it is restart-safe only *within a running
  process* (it survives an in-flight `XAUTOCLAIM` reclaim, not a restart). That
  in-memory limitation was deliberately scoped for the throwaway POC bean and is
  documented at its dedupe set.

So read the result as: **the design is proven restart-safe** (nothing lost,
nothing double-applied under real crashes). Making the *Java service* restart-safe
is the real risk-engine consumer's job — swapping the in-memory set for a durable
processed-events store exactly like the one this proof uses.

## How to run

```bash
cd Event-Driven-Trading-Ledger-Risk-Analytics-Platform/poc/native-kill-restart
python run_proof.py
```

Expected tail: `PHASE 5 TASK 5 PROOF PASSED`. Exit code is non-zero on any failure.

By default the script **starts its own `redis-server`** on an ephemeral port
(with persistence disabled) and tears it down at the end, so it leaves no
artifacts. Requirements:

- a `redis-server` binary on `PATH`, **or**
- an already-running Redis, targeted with:

  ```bash
  python run_proof.py --no-spawn --host 127.0.0.1 --port 6379
  ```

## Files

| File | Role |
|------|------|
| `run_proof.py` | Orchestrator: spawns Redis, seeds trades, drives both kill/restart cycles, asserts the done-when. |
| `relay_proc.py` | Killable outbox relay (publish-then-mark-sent) — the Task 2 subject under test. |
| `consumer_proc.py` | Killable idempotent consumer (XREADGROUP + durable dedupe + XAUTOCLAIM reclaim) — the Task 3 subject. |
| `store.py` | Shared SQLite store: outbox rows + **durable** consumer dedupe/projection. |
| `seed.py` | Deterministic trades + the single-delivery baseline the proof asserts against. |
| `redis_client.py` | Thin adapter over `redis-py` (only the stream commands used here). |

## Mapping proof → production code

| Proof piece | Production equivalent |
|-------------|-----------------------|
| `relay_proc.py` | `services/ledger-core` `OutboxRelay` (publish-then-mark-sent) |
| `consumer_proc.py` | `services/ledger-core` `Phase5PocConsumer` (group `cg:phase5-poc`) |
| stream fields `{event_type, schema_version, event}` | `OutboxRelay.toFields` / market-data producer convention |
| persisted `processed_events` dedupe | durable processed-events store the real `cg:risk-engine` consumer must add |
| `redis_client.py` | Redis Streams (`docs/contracts/streams/redis-streams.md`) |

## Limitations (intentional)

- SQLite stands in for PostgreSQL; the outbox/dedupe **pattern** is identical.
- Single account/one symbol-set workload chosen for a deterministic baseline.
- Kills are deterministic self-`exit(137)` at the exact gap under test (rather
  than a race-y external `SIGKILL`), so the proof is reproducible in CI. The
  effect on Redis/SQLite state is identical to an external hard kill at that
  instant.
