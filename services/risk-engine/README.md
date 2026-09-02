# risk-engine (Python / FastAPI)

The Risk Engine consumes committed ledger postings and market prices, computes
portfolio risk metrics, and publishes them for the live UI.

- **FastAPI app** (`app/main.py`) — health/observability endpoints.
- **Stream worker** (`app/worker.py`) — the Phase 6 consumer/publisher.

## Endpoints
- `GET /health`, `GET /healthz` — liveness/readiness JSON.
- `GET /` — service metadata.

## Phase 6 — risk metrics (portfolio value, P&L, volatility, VaR, Sharpe)

The worker is the real `cg:risk-engine` consumer:

- **Consumes** `ledger.updates` (`LedgerUpdated.v1`) on group `cg:risk-engine`,
  and `market.ticks` (`TickReceived.v1`) to keep a latest-price cache.
- **Recompute model:**
  - *2A (ledger-driven):* each applied ledger event recomputes and publishes
    immediately, so portfolio value / P&L update the instant a trade posts.
  - *2B (throttled tick-driven):* a throttle samples portfolio value into a
    durable rolling `pv_history` every `RISK_RECOMPUTE_INTERVAL_MS` (default
    1000ms). The resulting portfolio-value return series drives volatility, VaR,
    and Sharpe, so risk metrics move with the market — not only when a trade
    posts. The throttle is the sole PV-series sampler.
  - Both paths **publish** `RiskComputed.v1` to `risk.updates`.
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
| `volatility`, `var`, `sharpe` | **Live** — computed over the throttle-sampled portfolio-value return series (`volatility` = population stddev of PV returns; `var` = `1.65 · volatility · PV`; `sharpe` = mean / volatility). Emitted as `0.0` until at least two PV returns have accrued (window still filling). |

A published `var: 0` therefore means **"not enough history yet"**, not "no risk".
VaR is **parametric only** (~95% one-sided, z = 1.65); **historical VaR is out of
scope**. The `RiskComputed.v1` contract requires all fields
(`additionalProperties:false`), so they are always present.

At the default 1000ms interval, a 30-return window needs ~31 seconds of ticks to
fill; tune `RISK_WINDOW_SIZE` / `RISK_RECOMPUTE_INTERVAL_MS` for faster demos.

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
