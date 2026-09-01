# ledger-core (Java / Spring Boot)

System of record. Double-entry posting, compliance checks, immutable audit log,
transactional outbox, and the Ledger REST API.

- REST contract: `docs/contracts/openapi/ledger.openapi.yaml`
- Publishes stream: `ledger.updates` (`LedgerUpdated.v1`)
- Store: PostgreSQL
- Status: Phase 0 placeholder (implemented in a later phase).
