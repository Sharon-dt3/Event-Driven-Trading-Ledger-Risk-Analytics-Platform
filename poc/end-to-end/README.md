# POC Spec — TradePulse End-to-End Pipeline

> Status: **Proof of concept, spec-style.** A runnable "walking skeleton" of the
> **entire** TradePulse platform: `market-data → ledger-core (outbox) →
> risk-engine → gateway`. It exercises all three Redis Streams and all four v1
> event types from the frozen contracts in `docs/contracts/`, using the same
> transactional-outbox + idempotent-consumer patterns proven in
> `../outbox-idempotency/` (whose modules it reuses).

## 1. Purpose & scope

The `outbox-idempotency` POC proved the **correctness core** in isolation. This POC
proves the **system integrates end-to-end**: an incoming market tick and a trade
request travel through every service boundary and produce a live risk update on the
browser-facing gateway — without losing, duplicating, or corrupting state.

In scope:
- Market data ingestion → `TickReceived.v1` on `market.ticks`.
- Trade request (`TradeRequested.v1`, REST body) → double-entry posting → outbox →
  `LedgerUpdated.v1` on `ledger.updates`.
- Risk recomputation (compute-on-change) → `RiskComputed.v1` on `risk.updates`.
- Gateway fan-out of `market.ticks` + `risk.updates` to clients.

Out of scope (unchanged from architecture non-goals): real order matching, auth
enforcement, network/throughput behavior, AWS deployment.

## 2. Component / data-flow model

```
                 market.ticks                     ledger.updates            risk.updates
 [market-data] ───────────────►(cg:risk-engine)                              
      │  TickReceived.v1        └───►[PriceCache]        ┌──►[risk-engine]───────────────►(cg:gateway)
      │                                                  │   RiskComputed.v1
      └───────────────►(cg:gateway)                      │
                                                         │
 TradeRequested.v1 (REST) ──►[ledger-core]──(outbox)──(relay)──► ledger.updates ──►(cg:risk-engine)
                              double-entry + audit                                   LedgerUpdated.v1
```

| Service | Consumes | Produces | Idempotency |
|---------|----------|----------|-------------|
| market-data | — | `TickReceived.v1` → `market.ticks` | n/a (source) |
| ledger-core | `TradeRequested.v1` (REST) | `LedgerUpdated.v1` via **outbox** → `ledger.updates` | `UNIQUE source_event_id` |
| risk-engine | `ledger.updates` (`cg:risk-engine`), `market.ticks` (prices) | `RiskComputed.v1` → `risk.updates` | dedupe by `event_id` |
| gateway | `market.ticks` + `risk.updates` (`cg:gateway`) | push to clients | dedupe by `event_id` |

## 3. Event-type coverage (contract traceability)

| Event type | Contract | Where it appears in this POC |
|------------|----------|------------------------------|
| `TickReceived.v1` | `docs/contracts/events/tick_received.v1.schema.json` | market-data → `market.ticks` |
| `TradeRequested.v1` | `docs/contracts/events/trade_requested.v1.schema.json` | REST input to ledger-core |
| `LedgerUpdated.v1` | `docs/contracts/events/ledger_updated.v1.schema.json` | outbox relay → `ledger.updates` |
| `RiskComputed.v1` | `docs/contracts/events/risk_computed.v1.schema.json` | risk-engine → `risk.updates` |

## 4. Risk metrics (illustrative for the POC)

- **Portfolio value** = seed cash + P&L.
- **P&L** = market value of positions (latest tick price × qty) − cost basis.
- **Volatility** = population stdev of portfolio-value returns.
- **VaR** (parametric, default per Phase 0) ≈ `1.65 × volatility × portfolio_value`
  (~95% one-sided).
- **Sharpe** = mean(returns) / stdev(returns) (risk-free = 0 for the POC).

These are simplified but structurally faithful; production formulas live in
`services/risk-engine`.

## 5. What the run proves (acceptance criteria)

`run_pipeline.py` asserts:

1. `market.ticks` received all produced ticks.
2. Every posted trade produced exactly one `LedgerUpdated` via the outbox
   (`je_count == ledger.updates length`).
3. risk-engine applied each ledger event once and emitted a `RiskComputed` per
   change (`risk.updates` non-empty; no duplicates applied).
4. Gateway pushed only `TickReceived` + `RiskComputed`, each event once.
5. All three streams and all expected streamed event types are present.
6. Double-entry invariant holds (`debits == credits`).

It also runs a **resilience pass**: an injected duplicate on `ledger.updates` and a
`SETID 0` replay must not change risk-engine's derived positions.

## 6. How to run

```bash
cd Event-Driven-Trading-Ledger-Risk-Analytics-Platform/poc/end-to-end
python run_pipeline.py
```

Expected tail: `END-TO-END PIPELINE PASSED`. Non-zero exit on any assertion failure.
No external services needed — the Redis Streams simulator from
`../outbox-idempotency/stream_bus.py` is reused for a deterministic proof.

## 7. Mapping POC → production services

| POC module | Production service |
|------------|--------------------|
| `market_data.produce_ticks` | `services/market-data` (Go, Finnhub/synthetic) |
| reused `ledger.Ledger` + `relay.relay_outbox` | `services/ledger-core` (Java/Spring, Postgres + CDC/outbox) |
| `risk_engine.RiskEngine` | `services/risk-engine` (Python/FastAPI) |
| `gateway.Gateway` | `services/gateway` (WS/SSE fan-out) |
| `stream_bus.StreamBus` | Redis Streams (`docs/contracts/streams/redis-streams.md`) |

## 8. Limitations (intentional)

- Synchronous, single-process; models delivery semantics and data flow, not latency
  or concurrency.
- Consumer dedupe uses in-memory sets (production: durable processed-events tables).
- Risk math is simplified; contracts and flow are the point of this POC.
