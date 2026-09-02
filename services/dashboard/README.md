# dashboard (React / Vite)

Phase 7 — the complete TradePulse trading UI. No mocks: every screen is wired to
the real Ledger REST, Risk REST, and the gateway SSE realtime feed.

## Screens
- **Login** — JWT auth against `POST /ledger/auth/login` (demo logins provided).
- **Live ticker** — streaming `market.ticks` via the gateway SSE feed.
- **Positions & balances** — `GET /ledger/positions`, `GET /ledger/balances`.
- **Trades** — submit (idempotent `request_id`) via `POST /ledger/trades`, shows
  posted/rejected outcome, and lists history (`GET /ledger/trades`) with a
  status filter.
- **Risk metrics** — live snapshot from `risk.updates` (SSE) plus `GET
  /risk/summary` and `GET /risk/var` (parametric).
- **Audit trail** — `GET /ledger/audit` (compliance/admin only; 403 is handled).

Each screen has explicit loading / empty / error states.

## Demo logins
| username | password | role |
|----------|----------|------|
| demo_trader | trader-pw | trader |
| viewer | viewer-pw | viewer |
| compliance | compliance-pw | compliance |
| admin | admin-pw | admin |

Default account: `acct_123` (seeded). Change it via the account box in the top bar.

## Routing & proxying
The SPA calls same-origin paths that are proxied to the backend services:
- `/ledger/*` → ledger-core (the `/ledger` prefix is stripped; the service
  serves `/auth`, `/trades`, `/balances`, `/positions`, `/audit`).
- `/risk/*` → risk-engine (served literally as `/risk/summary`, `/risk/var`).
- `/stream` → gateway SSE feed.

Dev proxying lives in `vite.config.js`; production proxying in `nginx.conf`.

## Run locally (dev)
```bash
npm install
npm run dev      # http://localhost:3000
```
Point the dev proxy at running services with `LEDGER_URL`, `RISK_URL`,
`GATEWAY_URL` if they are not on the default localhost ports.

## Full live story (docker compose)
From `infra/`:
```bash
docker compose up --build
# open http://localhost:3000, sign in as demo_trader,
# submit a trade, and watch ticks + risk update live.
```

## Lint & build
```bash
npm run lint
npm run build
```

## Endpoints served by this container
- `/health` — nginx JSON status.
