# gateway (Go)

Phase 1 skeleton for the Realtime Gateway. Later phases consume `market.ticks`
and `risk.updates` from Redis Streams and fan them out to browsers over WS/SSE.

## Endpoints
- `GET /health`, `GET /healthz` — liveness/readiness JSON.
- `GET /ws` — placeholder (501) until realtime fan-out is implemented.
- `GET /` — service metadata.

## Conventions
- Structured JSON logs to stdout (`slog`), including `service` and `correlation_id`.
- Reads/generates and echoes `X-Correlation-ID`.
- Shared HTTP/observability helpers live in `../common-go/httpkit` (correlation
  middleware, request logging, JSON + health/root handlers).

## Run locally
```bash
PORT=8084 go run .
```

## Test
```bash
go test ./...
```
