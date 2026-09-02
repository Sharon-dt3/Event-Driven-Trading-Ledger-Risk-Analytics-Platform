# dashboard (React / Vite)

Phase 1 skeleton for the TradePulse Dashboard. Later phases add auth, protected
routes, portfolio/trades/audit views, and live updates over WS/SSE.

## Endpoints
- `/health` — served by nginx in the container image (JSON status).

## Run locally
```bash
npm install
npm run dev      # http://localhost:3000
```

## Lint & build
```bash
npm run lint
npm run build
```
