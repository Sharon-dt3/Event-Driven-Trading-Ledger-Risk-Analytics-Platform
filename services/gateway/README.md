# gateway (WS/SSE — Go or Node, TBD)

Browser-facing fan-out. Consumes `market.ticks` and `risk.updates` and pushes
`TickReceived.v1` / `RiskComputed.v1` to authenticated clients, scoped by
account/role. May be folded into an existing service during implementation.

- Consumes streams: `market.ticks`, `risk.updates`
- Serves: `/ws` (WebSocket) or SSE
- Status: Phase 0 placeholder (implemented in a later phase).
