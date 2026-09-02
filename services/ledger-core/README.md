# ledger-core (Java / Spring Boot)

Phase 4 **Ledger & Compliance Core** — the system-of-record. A SOLID, clean-
architecture double-entry ledger with compliance rules, an immutable audit log,
a transactional outbox, and JWT-secured REST endpoints.

## Architecture (clean layers)
```
web (controllers, security, JWT)         ← HTTP + auth boundary
  → application/use-cases (LedgerService) ← orchestration + @Transactional
    → domain (ComplianceRules, DTOs)      ← business rules, no framework deps
    → ledger (LedgerRepository)           ← SQL / persistence
```
- **Controllers** (`web/`) handle HTTP, validation, and status mapping only.
- **LedgerService** coordinates the atomic write and idempotency.
- **ComplianceRules** (`domain/`) owns the reject/accept policy — add new rules
  here without touching orchestration (open/closed).
- **LedgerRepository** owns all SQL; invariants (double-entry, idempotency) are
  enforced by the DB schema too (UNIQUE `source_event_id`, debit/credit checks).

## Trade posting use-case
Each accepted trade writes, in **one DB transaction**:
1. the `trades` row,
2. a balanced double-entry `journal_entries` + two `journal_lines`,
3. the `accounts.cash_balance` update,
4. an `audit_log` row,
5. an `outbox_events` row carrying a `LedgerUpdated.v1` envelope.

Compliance rules reject (but still **audit**) when a trade would:
- drive cash negative → `NEGATIVE_CASH`;
- exceed the configured position limit → `MAX_POSITION_EXCEEDED`.

**Idempotency (Phase 4 "done when"):** duplicate `request_id`s never double-post.
Enforced in code (return the original outcome) and by the database
(`journal_entries.source_event_id UNIQUE`). Proven at the service layer and
end-to-end over HTTP (`201` then `200`, one journal entry, unchanged cash).

## REST endpoints (behind ALB `/ledger`)
- `POST /auth/login` — exchange credentials for a JWT (`{access_token, token_type, role}`).
- `POST /trades` — submit a trade (idempotent by `request_id`). `201` posted,
  `409` rejected-by-compliance (still audited).
- `GET /trades?account_id=&status=` — trade history.
- `GET /balances?account_id=` — cash balances.
- `GET /positions?account_id=` — net position + average buy price per instrument.
- `GET /audit?account_id=` — immutable audit log (**compliance/admin** roles only).
- `GET /health`, `GET /` — liveness + metadata (public).

## Auth
Stateless **JWT (HS256)**. The service both mints (at `/auth/login`) and validates
tokens with a shared secret; the `role` claim maps to a Spring Security authority.
Demo credentials (POC only): `demo_trader/trader-pw`, `viewer/viewer-pw`,
`compliance/compliance-pw`, `admin/admin-pw`.

## Configuration (env)
| Var | Default | Purpose |
|-----|---------|---------|
| `SERVER_PORT` | `8082` | HTTP port. |
| `SPRING_DATASOURCE_URL` | `jdbc:postgresql://localhost:5432/tradepulse` | DB URL. |
| `SPRING_DATASOURCE_USERNAME` / `_PASSWORD` | `tradepulse` | DB creds. |
| `LEDGER_JWT_SECRET` | dev secret (rotate!) | HMAC signing key. |
| `LEDGER_JWT_TTL_SECONDS` | `3600` | Token lifetime. |
| `LEDGER_MAX_POSITION` | `1000000` | Max absolute net position per symbol. |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis endpoint for the `ledger.updates` stream publisher (Phase 5). |
| `LEDGER_STREAM_ENABLED` | `false` | Master switch for the outbox→Redis relay (plumbing only in Phase 5 Task 1). |
| `LEDGER_STREAM_NAME` | `ledger.updates` | Target Redis stream key for `LedgerUpdated.v1`. |
| `LEDGER_STREAM_POLL_INTERVAL_MS` | `1000` | (Future relay) outbox poll cadence. |
| `LEDGER_STREAM_BATCH_SIZE` | `100` | (Future relay) max outbox rows drained per poll. |

## Build & test
```bash
mvn -B verify
```
Tests run on **H2 in PostgreSQL mode** via Flyway (the same migrations used
against real Postgres), so double-entry, compliance, and idempotency invariants
are proven **without Docker**.

## Scope notes
Auth uses an in-memory demo credential store; a production build would
authenticate against the `users` table with hashed passwords. The outbox relay
(publishing `LedgerUpdated.v1` to Redis) is a separate component; this service
guarantees the event is written atomically with the ledger change.
```
