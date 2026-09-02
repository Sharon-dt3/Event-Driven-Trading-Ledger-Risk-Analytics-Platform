# Event-Driven-Trading-Ledger-Risk-Analytics-Platform

TradePulse is a fintech trading platform that simulates real-time trading. It uses Redis Streams to process market data, records trades in a secure double-entry ledger, and automatically calculates risk metrics like P&amp;L, volatility, VaR, and Sharpe ratio, which are displayed on a live dashboard.

## Local platform (Docker)

Requires a host with a working Docker daemon (able to run containers).

```bash
make up      # build + start all services in the background
make ps      # show container status (look for "healthy")
make logs    # tail logs for all services
make down    # stop and remove containers + volumes
```

Health endpoints once the stack is up:

| Service       | URL                                   |
|---------------|---------------------------------------|
| market-data   | http://localhost:8081/health          |
| ledger-core   | http://localhost:8082/actuator/health |
| risk-engine   | http://localhost:8083/health          |
| gateway       | http://localhost:8084/health          |
| dashboard     | http://localhost:3000/health          |

## Native verification (no Docker required)

In restricted or nested-container environments the Docker daemon may be unable to
extract image layers (`failed to register layer: unshare: operation not permitted`),
so `make up` cannot run. To verify that every service still compiles, resolves its
dependencies, and passes its unit tests, run the native verification instead:

```bash
make verify-native          # skip services whose toolchain isn't installed
make verify-native-strict   # treat a missing toolchain as a failure
```

What it checks per service:

| Service                | Toolchain | Checks                          |
|------------------------|-----------|---------------------------------|
| market-data, gateway   | Go 1.22   | `go build` + `go vet` + `go test` |
| risk-engine            | Python    | venv + install deps + `pytest`  |
| ledger-core            | Java 17   | `mvn verify` (or `./mvnw`)      |
| dashboard              | Node      | `npm ci` + `npm run build` (+ lint) |

The script prints a per-service PASS / SKIP / FAIL summary and exits non-zero if any
service fails. It lives at [`scripts/verify-native.sh`](scripts/verify-native.sh).
