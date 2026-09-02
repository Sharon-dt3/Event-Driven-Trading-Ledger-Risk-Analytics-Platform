# ledger-core (Java / Spring Boot)

Phase 1 skeleton for the Ledger & Compliance Core (system of record). Later phases
add double-entry posting, compliance checks, audit log, transactional outbox, and
the `/trades`, `/balances`, `/positions`, `/audit` REST APIs.

## Endpoints
- `GET /actuator/health` — actuator health (used by compose/CI probes).
- `GET /health` — simple JSON health.
- `GET /` — service metadata.

## Conventions
- Structured JSON logs via logback + logstash encoder, including `service` and `correlation_id`.
- `CorrelationIdFilter` reads/generates and echoes `X-Correlation-ID` and binds it to the MDC.

## Run locally
```bash
mvn spring-boot:run
```

## Test
```bash
mvn -B -ntp verify
```
