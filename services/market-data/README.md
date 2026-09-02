# market-data (Go)

Market Data Service. Generates normalized market **ticks** and publishes them to
the `market.ticks` Redis stream as `TickReceived.v1` envelopes (see
`docs/contracts/events/tick_received.v1.schema.json`).

Phase 3 implements **synthetic** tick generation (a bounded random walk per
symbol). A `finnhub` source is recognized but live WS ingestion is not enabled
in this build, so it transparently **falls back to synthetic** generation.

## Endpoints
- `GET /health`, `GET /healthz` — liveness/readiness JSON.
- `GET /` — service metadata.

## What it publishes
- Stream: `market.ticks` (configurable via `MARKET_DATA_STREAM`).
- Each `XADD` entry carries fields:
  - `event_type` = `TickReceived`
  - `schema_version` = `1`
  - `event` = the full JSON envelope (`TickReceived.v1`)
- Streams are trimmed with an approximate cap (`XADD ... MAXLEN ~ <n>`).

## Configuration (env vars)
| Variable | Default | Purpose |
|----------|---------|---------|
| `PORT` | `8081` | HTTP port for health/metadata. |
| `REDIS_ADDR` | `localhost:6379` | Redis host:port for stream publishing. |
| `MARKET_DATA_STREAM` | `market.ticks` | Target stream name. |
| `MARKET_DATA_STREAM_MAXLEN` | `100000` | Approximate stream cap (`MAXLEN ~`). |
| `MARKET_DATA_SYMBOLS` | `AAPL,MSFT,GOOG` | Comma-separated symbols to emit. |
| `MARKET_DATA_TICK_INTERVAL_MS` | `1000` | Interval between tick rounds. |
| `MARKET_DATA_SOURCE` | `synthetic` | `synthetic` or `finnhub` (falls back to synthetic). |
| `FINNHUB_API_KEY` | _(unset)_ | Reserved for future live ingestion. |
| `LOG_LEVEL` | `INFO` | `DEBUG` logs every published tick. |

## Conventions
- Structured JSON logs to stdout (`slog`), including `service` and `correlation_id`.
- Reads/generates and echoes `X-Correlation-ID` on HTTP.
- Shared HTTP/observability helpers live in `../common-go/httpkit`.
- Redis access uses the standard [`go-redis`](https://github.com/redis/go-redis)
  client (`XADD` with `MAXLEN ~`, `PING`). Unit tests stay fully offline by
  mocking the `publisher` interface, so no live Redis is needed in CI.

## Run locally
```bash
# with a local Redis on :6379
REDIS_ADDR=localhost:6379 PORT=8081 go run .
```

## Test
```bash
go test ./...
```
