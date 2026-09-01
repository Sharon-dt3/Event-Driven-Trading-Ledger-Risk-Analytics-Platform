# Repository Structure (Phase 0)

```
services/
  market-data/     # Go — ingest Finnhub WS / synthetic ticks, publish market.ticks
  ledger-core/     # Java Spring Boot — double-entry ledger, audit, outbox, REST
  risk-engine/     # Python FastAPI — portfolio value, P&L, volatility, VaR, Sharpe
  gateway/         # WS/SSE fan-out of market.ticks + risk.updates (Go or Node, TBD)
  dashboard/       # React — protected UX, live updates
infra/             # Docker Compose (local) + AWS IaC (ECS/RDS/ElastiCache/ALB/CloudFront)
docs/
  contracts/       # Frozen v1 contracts (events, openapi, streams)
  repo-structure.md
```

Each service directory is intentionally a thin placeholder in Phase 0. Services
are implemented in later phases against the **frozen** contracts under
`docs/contracts/`.
