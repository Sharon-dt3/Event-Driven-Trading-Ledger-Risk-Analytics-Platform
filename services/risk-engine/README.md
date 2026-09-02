# risk-engine (Python / FastAPI)

The Risk Engine consumes committed ledger postings and market prices, computes
portfolio risk metrics, and publishes them for the live UI.

- **FastAPI app** (`app/main.py`) — health/observability endpoints.
- **Stream worker** (`app/worker.py`) — the Phase 6 consumer/publisher.

## Endpoints
- `GET /health`, `GET /healthz` — liveness/readiness JSON.
- `GET /` — service metadata.

## Phase 6 — thin slice (portfolio value + P&L)

The worker is the real `cg:risk-engine` consumer:

- **Consumes** `ledger.updates` (`LedgerUpdated.v1`) on group `cg:risk-engine`,
  and `market.ticks` (`TickReceived.v1`) to keep a latest-price cache.
- **Recomputes on each ledger event** (ledger-driven; ticks only refresh the
  price cache in this slice), then **publishes** `RiskComputed.v1` to
  `risk.updates`.
- **Idempotent & restart-safe by construction:** every consumed event is written
  to a durable SQLite log keyed by envelope `event_id` (`INSERT OR IGNORE`), and
  cash/positions are *derived by SQL* over that deduped log. Dedupe **is** the
  projection's idempotency — no separate flag — and because the log is on disk it
  survives a process restart. This is the durable dedupe the Phase 5 scoping note
  reserved for the real consumer, so the shipped service has the property (not
  just the design proven by `poc/native-kill-restart`).

### Metrics scope (honest boundary)

| Metric | Status in the thin slice |
|--------|--------------------------|
| `portfolio_value`, `pnl` | **Live** — computed from cash + marked positions. |
| `volatility`, `var`, `sharpe` | **Emitted per contract but `0`** until the price-history / tick-driven recompute path is added. |

A published `var: 0` therefore means **"not yet computed"**, not "no risk". The
`RiskComputed.v1` contract requires all fields (`additionalProperties:false`), so
they are always present.

**Price fallback:** a symbol's mark is the latest `market.ticks` price, or the
trade's own price when no tick has arrived yet — so PV/PnL are meaningful before a
market feed exists (PnL is `0` at trade time).

## Run

```bash
pip install -r requirements-dev.txt

# API (health/observability)
uvicorn app.main:app --reload --port 8083

# Stream worker (needs Redis; reads REDIS_URL, default redis://localhost:6379/0)
python -m app.worker            # loop
python -m app.worker --once     # single drain cycle (for scripted checks)
```

Key env vars: `REDIS_URL`, `RISK_DB_PATH`, `RISK_SEED_CASH`,
`RISK_CONSUMER_GROUP` (default `cg:risk-engine`), `RISK_MIN_IDLE_MS`.

## Lint & test

```bash
ruff check .
pytest
```

Tests are offline (no Redis): they cover pure metric math, the durable dedupe
(including **survives-restart**), and the consumer's event→metric decision. The
end-to-end live wire proof (real ledger event → `risk.updates`) is exercised
against a running Redis as described in the Phase 6 verification notes.

## Conventions
- Structured JSON logs to stdout, including `service` and `correlation_id`.
- Reads/generates and echoes `X-Correlation-ID`.
```
