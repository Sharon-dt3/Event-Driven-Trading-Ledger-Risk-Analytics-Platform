# TradePulse — Phase 0 Contracts (Frozen v1)

This directory contains the **contract-first, frozen v1 interfaces** that let each
service be built independently. Nothing here may change without a version bump
(see the versioning policy below).

## Layout

```
docs/contracts/
  events/        # Event envelope + per-event JSON Schemas (v1) and sample payloads
  openapi/       # REST contracts: Ledger API and Risk API (OpenAPI 3.1)
  streams/       # Redis Streams topology, consumer groups, replay rules
```

## What is frozen in Phase 0

1. **Event envelope** — every event on Redis Streams shares one envelope
   (`events/envelope.schema.json`).
2. **Event schemas v1**:
   - `TickReceived.v1`   → stream `market.ticks`
   - `TradeRequested.v1` → REST body (optionally streamed)
   - `LedgerUpdated.v1`  → stream `ledger.updates` (canonical name; `TradePosted` is an alias)
   - `RiskComputed.v1`   → stream `risk.updates`
3. **OpenAPI contracts** — Ledger API (`openapi/ledger.openapi.yaml`) and Risk API
   (`openapi/risk.openapi.yaml`).
4. **Redis Streams topology** — streams, consumer groups, replay rules
   (`streams/redis-streams.md`).

## Canonical decisions locked for v1

| Decision | Choice |
|----------|--------|
| Ledger event name | `LedgerUpdated.v1` (alias: `TradePosted.v1`) |
| VaR default method | `parametric` (v1 default; `historical` optional) |
| Envelope timestamp format | RFC3339 / ISO-8601 UTC (`date-time`) |
| ID format | UUID (`event_id`, `correlation_id`) |

## Validation

Run the validator from the repo root to confirm every sample payload validates
against its schema (the Phase 0 "done" gate):

```bash
python utils/validate_contracts.py
```

## Proof of concept (gap + solution)

A runnable, dependency-light POC proving the correctness core (transactional
outbox + idempotent consumers + double-entry) survives crashes, duplicate
delivery, and stream replay lives under `poc/outbox-idempotency/`:

```bash
cd poc/outbox-idempotency && python run_scenarios.py
```

A whole-project, spec-style end-to-end POC (market-data → ledger → risk-engine →
gateway, exercising all three streams and all four v1 event types) lives under
`poc/end-to-end/`:

```bash
cd poc/end-to-end && python run_pipeline.py
```

## Versioning policy

- Event names carry a major version suffix (`.v1`); the envelope also carries
  `schema_version`.
- **Additive** (backward-compatible) changes may extend `data` without a version bump.
- **Breaking** changes require a new major version (`.v2`) and dual-publish during migration.
- REST APIs are versioned via path prefix when the first breaking change is introduced.
