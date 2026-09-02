# TradePulse — Redis Streams Topology (Frozen v1)

Event bus for TradePulse. Three streams provide at-least-once delivery via
consumer groups; **all consumers must be idempotent**.

## Streams

| Stream | Producer | Consumer group(s) | Event type | Purpose |
|--------|----------|-------------------|------------|---------|
| `market.ticks` | market-data | `cg:risk-engine`, `cg:gateway` | `TickReceived.v1` | Normalized market ticks. |
| `ledger.updates` | ledger-core (outbox publisher) | `cg:risk-engine` | `LedgerUpdated.v1` | Committed ledger postings. |
| `risk.updates` | risk-engine | `cg:gateway` | `RiskComputed.v1` | Computed risk metrics for live UI. |

## Consumer groups

- Group naming: `cg:<service>` (e.g. `cg:risk-engine`, `cg:gateway`).
- Consumer naming within a group: `<service>-<instance-id>` (e.g. `risk-engine-1`).
- Created with `XGROUP CREATE <stream> <group> $ MKSTREAM` (start at new messages;
  use `0` when a group must process from the beginning).
- Read with `XREADGROUP GROUP <group> <consumer> COUNT <n> BLOCK <ms> STREAMS <stream> >`.

### Reserved vs throwaway groups on `ledger.updates`

- **`cg:risk-engine` is reserved** for the real risk-engine consumer and is the
  only production group on `ledger.updates`. It is intentionally **not** created
  yet: it must be introduced by the risk-engine service itself so that, once it
  exists, it sees every committed `LedgerUpdated.v1` from its creation point
  onward. Nothing else may borrow this group name.
- **`cg:phase5-poc` is a throwaway proof group** used only to prove idempotent,
  reclaim-safe consumption during Phase 5. Its consumer
  (`Phase5PocConsumer`, group `cg:phase5-poc`, consumer `phase5-poc-1`) is inert
  by default (`ledger.consumer.enabled=false`) and drives no Redis traffic until
  explicitly enabled. It keeps its dedupe state **in memory**, so it is not
  restart-safe by design — it exists to validate the mechanics, not to hold
  durable projection state. It must be deleted once the real consumer lands
  (`XGROUP DESTROY ledger.updates cg:phase5-poc`) and must never be relied on in
  production.

## Delivery & idempotency

- **At-least-once** delivery. Consumers dedupe by envelope `event_id`.
- The ledger additionally dedupes trade posting by `data.source_event_id`
  (== `TradeRequested.request_id`), enforced by a `UNIQUE` constraint.
- Consumers **`XACK`** an entry only after successful processing.

### Two dedupe keys, two distinct jobs

The platform deliberately dedupes on **two different keys** at two different
boundaries; they are not interchangeable:

| Key | Scope | Owner | Guards against | Enforcement |
|-----|-------|-------|----------------|-------------|
| `event_id` | Per **published event** (envelope-level, unique per `XADD`) | Every stream consumer | **Redelivery** of the same event — at-least-once replays, `XAUTOCLAIM` reclaims, and full replays | Consumer-side dedupe (e.g. a processed-events set/table); a duplicate `event_id` is a no-op |
| `source_event_id` | Per **originating command** (`== TradeRequested.request_id`) | ledger-core write path | **Double-posting** from a retried/duplicate client request that would otherwise create two distinct ledger entries | DB `UNIQUE` constraint on `journal_entries.source_event_id` |

Why both are needed:

- `event_id` protects the **transport**: the same committed `LedgerUpdated.v1`
  can be delivered more than once, so consumers key on `event_id` to apply each
  event's effect exactly once regardless of how many times it arrives.
- `source_event_id` protects the **write**: two *different* client submissions
  (each a distinct `event_id`) can carry the *same* `request_id`, and the ledger
  must post that trade only once. This is caught before an event is ever emitted.
- They operate at opposite ends: `source_event_id` prevents duplicate *events
  from being produced*; `event_id` prevents a produced event's effect from being
  *applied twice by a consumer*. Neither alone is sufficient.

## Outbox relay ordering & runbook

`ledger.updates` is fed by ledger-core's **transactional-outbox relay**
(`OutboxRelay`), not by direct `XADD` from the request path. Each accepted trade
writes its `LedgerUpdated.v1` envelope to the `outbox_events` table **in the same
DB transaction** as the ledger change, guaranteeing the event exists if and only
if the posting committed. A scheduled worker then relays unsent rows to Redis.

### Ordering rationale (publish-then-mark-sent)

- The relay drains `outbox_events WHERE sent=false` **oldest-first** and, per
  row, **publishes to the stream first and only then flips `sent=true`**
  (publish-then-mark-sent).
- If a publish fails, the batch **stops without marking that row**, so it and
  every later row stay unsent and are retried on the next cycle. This preserves
  **per-producer ordering** on the stream: a later ledger event is never marked
  sent (nor allowed to jump ahead) while an earlier one is still unpublished.
- The ordering also makes delivery **at-least-once**: a crash *between* publish
  and mark re-publishes the row next cycle (a duplicate on the stream), which
  consumers absorb via `event_id` dedupe. The alternative — mark-then-publish —
  would be at-most-once and could silently drop a committed event, so it is
  rejected.
- The relay is gated by `ledger.stream.enabled` (off by default) and never marks
  rows sent while disabled (publishing is a no-op), so disabling it cannot drop
  events.

### Operational runbook

- **Enable the relay:** set `ledger.stream.enabled=true` (env
  `LEDGER_STREAM_ENABLED=true`) on ledger-core; tune `ledger.stream.poll-interval-ms`
  and `ledger.stream.batch-size` as needed.
- **Enable the POC consumer (proof only):** set `ledger.consumer.enabled=true`
  (env `LEDGER_CONSUMER_ENABLED=true`). It creates `cg:phase5-poc` with
  `MKSTREAM`, reads with `XREADGROUP ... >`, dedupes by `event_id`, applies a
  trivial projection, then `XACK`s. Each cycle it first reclaims stale pending
  entries (idle beyond `ledger.consumer.min-idle-ms`, an `XAUTOCLAIM`-equivalent)
  and reprocesses them; dedupe makes an already-applied reclaim a no-op.
- **Inspect backlog:** `XLEN ledger.updates`, and
  `XPENDING ledger.updates cg:phase5-poc` for un-acked entries.
- **Recover a crashed consumer:** stale pending entries are auto-reclaimed by a
  live consumer after `min-idle-ms`; no manual `XCLAIM` is normally required.
- **Tear down the POC:** disable the consumer, then
  `XGROUP DESTROY ledger.updates cg:phase5-poc`. Do **not** destroy or reuse
  `cg:risk-engine`.

## Pending / reclaim

- Unacked entries are reclaimed after a visibility timeout using
  `XAUTOCLAIM <stream> <group> <consumer> <min-idle-ms> 0` (or `XPENDING` +
  `XCLAIM`).
- Recommended `min-idle-ms`: 30000 (tune per service).

## Replay rules

- To reprocess, reset a group's last-delivered ID:
  `XGROUP SETID <stream> <group> <id>` (use `0` for full replay).
- Replay is safe because processing is idempotent (dedupe by `event_id` /
  `source_event_id`); ledger state is never duplicated.
- Replay should be performed one consumer group at a time to bound load.

## Retention / trimming

- Each stream is trimmed with an approximate cap: `XADD <stream> MAXLEN ~ <N> ...`.
- Retention (time or length) **must exceed the maximum expected consumer
  downtime** so no committed event is trimmed before all groups consume it.
- Suggested starting caps (tune in Phase 10): `market.ticks` ~100000,
  `ledger.updates` ~50000, `risk.updates` ~50000.
