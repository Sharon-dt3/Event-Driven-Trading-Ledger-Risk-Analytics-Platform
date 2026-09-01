# risk-engine (Python / FastAPI)

Computes portfolio value, P&L, volatility, VaR (default parametric), and Sharpe.
Consumes ledger postings and price snapshots; publishes computed metrics.

- REST contract: `docs/contracts/openapi/risk.openapi.yaml`
- Consumes streams: `ledger.updates`, `market.ticks`
- Publishes stream: `risk.updates` (`RiskComputed.v1`)
- Status: Phase 0 placeholder (implemented in a later phase).
