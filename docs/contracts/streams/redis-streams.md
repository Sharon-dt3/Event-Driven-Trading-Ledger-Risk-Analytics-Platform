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

## Delivery & idempotency

- **At-least-once** delivery. Consumers dedupe by envelope `event_id`.
- The ledger additionally dedupes trade posting by `data.source_event_id`
  (== `TradeRequested.request_id`), enforced by a `UNIQUE` constraint.
- Consumers **`XACK`** an entry only after successful processing.

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
