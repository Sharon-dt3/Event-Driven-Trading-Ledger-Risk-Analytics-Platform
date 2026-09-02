# market-data (Go)

Phase 1 skeleton for the Market Data Service. Later phases add Finnhub WS /
synthetic tick ingestion and publishing to the `market.ticks` Redis stream.

## Endpoints
- `GET /health`, `GET /healthz` — liveness/readiness JSON.
- `GET /` — service metadata.

## Conventions
- Structured JSON logs to stdout (`slog`), including `service` and `correlation_id`.
- Reads/generates and echoes `X-Correlation-ID`.
- Shared HTTP/observability helpers live in `../common-go/httpkit` (correlation
  middleware, request logging, JSON + health/root handlers).

## Run locally
```bash
PORT=8081 go run .
```

## Test
```bash
go test ./...
```
