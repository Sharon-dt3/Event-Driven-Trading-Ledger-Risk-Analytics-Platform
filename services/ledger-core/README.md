# ledger-core (Java / Spring Boot)

System-of-record for TradePulse: the double-entry ledger, audit log, and
transactional outbox. Phase 2 adds the real PostgreSQL data model with
correctness invariants enforced by the database.

## Data model (Flyway migrations)

Migrations live in `src/main/resources/db/migration` and run automatically on
startup (and in tests):

| Migration | Tables |
|-----------|--------|
| `V1__users_accounts.sql` | `users`, `accounts` (cash as `NUMERIC`, non-negative CHECK) |
| `V2__trades.sql` | `trades` (`request_id` UNIQUE idempotency key; side/status/amount CHECKs; indexes) |
| `V3__journal.sql` | `journal_entries` (`source_event_id` UNIQUE), `journal_lines` (debit-XOR-credit CHECK) |
| `V4__audit_outbox.sql` | `audit_log`, `outbox_events` |
| `V5__seed_demo_account.sql` | demo trader + funded `acct_123` ($10,000) |

### Invariants (enforced in the DB, not just code)
- **Idempotency:** `trades.request_id` and `journal_entries.source_event_id` are `UNIQUE` — the same trade can never post twice.
- **Double-entry:** every posting writes mirrored debit/credit lines; each line is a debit XOR a credit; debits == credits.
- **No negative cash:** `accounts.cash_balance >= 0`; over-spend is rejected (and audited) with `NEGATIVE_CASH`.
- **Exact money:** `NUMERIC(20,4)` / `BigDecimal`, never floats.

## Endpoints (see docs/contracts/openapi/ledger.openapi.yaml)
- `POST /trades` — submit a trade. `201` posted, `200` idempotent replay, `409` rejected (still audited), `404` unknown account.
- `GET /trades?account_id=&status=` — trade history.
- `GET /balances?account_id=` — cash balances.
- `GET /audit?account_id=` — immutable audit log.
- `GET /health` — liveness.

## Run locally (real Postgres)
```bash
# from repo root, with Docker available
make up
```
Uses `SPRING_DATASOURCE_URL/USERNAME/PASSWORD` from `infra/docker-compose.yml`.

## Test (no Docker required)
```bash
mvn -B verify
```
Tests run against **H2 in PostgreSQL mode** with the same Flyway migrations, and
prove: debits = credits, audit written, and idempotent no-double-post.
