# risk-engine (Python / FastAPI)

The Risk Engine consumes committed ledger postings and market prices, computes
portfolio risk metrics, and publishes them for the live UI.

- **FastAPI app** (`app/main.py`) — health/observability endpoints.
- **Stream worker** (`app/worker.py`) — the Phase 6 consumer/publisher.

## Endpoints
- `GET /health`, `GET /healthz` — liveness/readiness JSON.
- `GET /` — service metadata.

### Read API (dashboard) — frozen contract `docs/contracts/openapi/risk.openapi.yaml`
- `GET /risk/summary?account_id=...` — latest `RiskSummary` (portfolio value,
  P&L, volatility, VaR, Sharpe, `computed_at`); `404` when nothing computed yet.
- `GET /risk/var?account_id=...` — `VarDetail` (parametric, ~95%, 1-day horizon).
  `method=historical` is rejected (`400`) as a documented deferral.

**Freshness model:** the read API serves the **last-published** snapshot from a
durable `risk_snapshots` table (written as each `RiskComputed.v1` is built and
published), so a dashboard fetch-on-load is coherent with the live
`risk.updates` stream — the REST answer matches the last event on the wire
rather than a fresh recompute that could diverge mid-throttle-interval. The API
process shares the worker's SQLite DB via `RISK_DB_PATH`.

**Error shape:** all error responses use the contract `Error` schema
(`{code, message}`) — including FastAPI request-validation failures (422), which
are reshaped from the framework default `{detail: [...]}`. This gives the
dashboard one uniform, contract-documented error shape across `400/404/422`.

**Path alignment:** the service serves the contract's literal `paths` keys
(`/risk/summary`, `/risk/var`). The `servers: /risk` entry is an edge-routing
annotation; the gateway/ALB `/risk` route must forward **path-preserving** (no
prefix strip), so the dashboard's contract URL (`/risk/summary`) reaches the
service path unchanged.

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

### Explainability layer (plain-language + optional AI)

`GET /risk/explain?account_id=...` turns the latest snapshot into plain-language
analysis for users without finance expertise (headline, per-metric explanations,
and caveats). It is **additive** and does not alter the frozen contracts.

- **Default (`mode` omitted or `mode=rule`)** — deterministic, rule-based text
  (module `app/explain.py`). No dependencies, fully unit-tested.
- **Optional `mode=llm`** — a **grounded** LLM rewrite (module `app/llm_explain.py`)
  that makes the same facts friendlier/conversational. The model is given only the
  already-computed numbers and facts and instructed to never invent figures or give
  advice; only prose is overlaid onto the authoritative deterministic structure.
  It is **off by default**, uses **no extra dependencies** (stdlib `urllib` against
  an OpenAI-compatible endpoint), and **falls back** to rule-based text on any
  error, so the endpoint never breaks. The response `mode` field reports what was
  actually produced (`rule` or `llm`).
- `GET /risk/explain/capabilities` → `{ "llm_enabled": bool }` lets the dashboard
  show its "AI explanation" toggle only when the server has the mode enabled.

LLM env vars (all optional): `RISK_LLM_ENABLED` (default `false`),
`RISK_LLM_API_KEY` (or `OPENAI_API_KEY`), `RISK_LLM_BASE_URL`
(default `https://api.openai.com/v1`), `RISK_LLM_MODEL` (default `gpt-4o-mini`),
`RISK_LLM_TIMEOUT_MS` (default `8000`).

**Dashboard read API:** the compute+publish path above is also exposed over REST
(`GET /risk/summary`, `GET /risk/var`) by serving the last-published snapshot, so
the dashboard can fetch current state on load and then track the live stream.

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
