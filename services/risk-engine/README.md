# risk-engine (Python / FastAPI)

Phase 1 skeleton for the Risk Engine. Later phases consume `ledger.updates` and
price snapshots derived from `market.ticks`, compute portfolio value / P&L /
volatility / VaR / Sharpe, and publish `risk.updates`.

## Endpoints
- `GET /health`, `GET /healthz` — liveness/readiness JSON.
- `GET /` — service metadata.

## Conventions
- Structured JSON logs to stdout, including `service` and `correlation_id`.
- Reads/generates and echoes `X-Correlation-ID`.

## Run locally
```bash
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8083
```

## Lint & test
```bash
ruff check .
pytest
```
