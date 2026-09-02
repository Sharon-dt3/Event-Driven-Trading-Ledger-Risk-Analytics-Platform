# gateway (Go)

Realtime gateway for TradePulse. Tails the `market.ticks` and `risk.updates`
Redis Streams and fans new events out to browsers over **Server-Sent Events
(SSE)**, so the dashboard sees live ticks and risk updates without polling.

## Endpoints
- `GET /health`, `GET /healthz` — liveness/readiness JSON.
- `GET /stream` — SSE feed. Emits two named events:
  - `event: ticks` — full `TickReceived.v1` envelope JSON (from `market.ticks`).
  - `event: risk`  — full `RiskComputed.v1` envelope JSON (from `risk.updates`).
  Consume with the browser `EventSource` API. Keep-alive comments are sent every
  15s; clients that fall behind are dropped rather than stalling the feed.
- `GET /ws` — legacy placeholder (501) that points callers to `/stream`.
- `GET /` — service metadata.

## Configuration (env)
- `PORT` (default `8084`)
- `REDIS_ADDR` (default `localhost:6379`) — e.g. `redis:6379` in compose.
- `MARKET_DATA_STREAM` (default `market.ticks`)
- `RISK_STREAM` (default `risk.updates`)

## How it works
A single background tailer runs a blocking `XREAD` from `$` (only new entries)
across both streams and publishes each entry's `event` field (the full envelope
JSON written by the producers) to an in-memory broker. Each `/stream` request
subscribes to that broker for the life of the connection. Redis outages are
retried transparently; `/health` stays up regardless.

## Conventions
- Structured JSON logs to stdout (`slog`), including `service` and `correlation_id`.
- Reads/generates and echoes `X-Correlation-ID`.
- Shared HTTP/observability helpers live in `../common-go/httpkit`.

## Run locally
```bash
REDIS_ADDR=localhost:6379 PORT=8084 go run .
# then: curl -N http://localhost:8084/stream
```

## Test
```bash
go test ./...
```
