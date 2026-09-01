# market-data (Go)

Ingests Finnhub WebSocket or synthetic ticks, normalizes them, and publishes
`TickReceived.v1` to the `market.ticks` Redis Stream.

- Contract: `docs/contracts/events/tick_received.v1.schema.json`
- Publishes stream: `market.ticks`
- Status: Phase 0 placeholder (implemented in a later phase).
