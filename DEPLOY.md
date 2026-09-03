# Deploying TradePulse behind a single URL

TradePulse is already designed to be reached through **one URL**. The dashboard
container runs nginx and reverse-proxies every backend API, so end users only
ever talk to the dashboard's port — never to the individual services.

```
                         ┌─────────────────────────────────────────┐
   http://<host>/  ───▶  │ dashboard (nginx + React SPA, port 3000) │
                         │                                          │
                         │  /            → React SPA (static)       │
                         │  /ledger/...  → ledger-core:8082         │
                         │  /risk/...    → risk-engine:8083         │
                         │  /stream      → gateway:8084 (SSE)       │
                         └──────────────────┬───────────────────────┘
                                            │ internal compose network
        ┌───────────────┬───────────────────┼───────────────┬───────────────┐
    market-data     ledger-core         risk-engine      risk-worker     gateway
     (Go)            (Java/Spring)        (Python)         (Python)        (Go)
        └──────── redis (streams) ───────────┴──────── postgres ──────────┘
```

The proxy rules live in [`services/dashboard/nginx.conf`](services/dashboard/nginx.conf)
(production) and [`services/dashboard/vite.config.js`](services/dashboard/vite.config.js)
(local dev). Because of this, **you do not expose ports 8081–8084 publicly** —
only the dashboard.

## Prerequisites

- A host with a working **Docker daemon** and the Docker Compose plugin.
- Ports: the public port you choose (default **80**) must be free on the host.

> Note: the Go services (`market-data`, `gateway`) and the full stack are built
> and run **inside Docker**, so you do not need Go/Java/Python installed on the
> host — only Docker.

## One-command deploy (single URL)

From the repository root:

```bash
# Serve the whole platform on http://<host>/  (port 80)
make deploy

# Or pick another public port, e.g. 3000:
PUBLIC_PORT=3000 make deploy

# Watch startup until services are healthy:
make deploy-ps
make deploy-logs

# Tear everything down (also removes volumes):
make deploy-down
```

Equivalent raw compose commands (if you prefer not to use make):

```bash
docker compose -f infra/docker-compose.deploy.yml up --build -d
docker compose -f infra/docker-compose.deploy.yml ps
docker compose -f infra/docker-compose.deploy.yml down -v
```

Then open the single URL:

```
http://<host>:${PUBLIC_PORT:-80}/
```

Everything — login, trades, positions, ticker, risk, audit, and the live SSE
feed — is served from that one origin.

## Configuration

Copy `.env.example` to `.env` in `infra/` to override defaults (DB credentials,
symbols, tick interval, log level). The deploy file also honors:

| Variable      | Default | Purpose                                   |
|---------------|---------|-------------------------------------------|
| `PUBLIC_PORT` | `80`    | Host port that serves the single URL      |

`LEDGER_STREAM_ENABLED` defaults to `true` in the deploy file so risk metrics
populate automatically from the ledger event stream.

## Putting it on a real domain (optional TLS)

For a public hostname with HTTPS, keep `PUBLIC_PORT` internal (e.g. 3000) and
put a TLS-terminating reverse proxy in front:

```
Internet ──▶ Caddy/Traefik/Nginx (443, TLS) ──▶ dashboard container (PUBLIC_PORT)
```

Point the proxy's upstream at `http://<host>:${PUBLIC_PORT}` and it will forward
all of `/`, `/ledger`, `/risk`, and `/stream` (SSE) unchanged. Ensure the proxy
does **not** buffer `/stream` so the live feed streams in real time.

## Why not expose each service separately?

You can (the dev compose `infra/docker-compose.yml` does, for debugging), but for
a deployment the single-URL model is simpler and safer: one origin, no CORS, no
per-service DNS, and the backends are not reachable from outside the network.
```
