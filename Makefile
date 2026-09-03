COMPOSE = docker compose -f infra/docker-compose.yml
COMPOSE_DEPLOY = docker compose -f infra/docker-compose.deploy.yml
COMPOSE_PUBLIC = docker compose -f infra/docker-compose.public.yml

.PHONY: up down logs ps build restart deploy deploy-down deploy-logs deploy-ps deploy-public deploy-public-down deploy-public-logs deploy-public-ps verify-native verify-native-strict clean

up:
	$(COMPOSE) up --build -d

build:
	$(COMPOSE) build

down:
	$(COMPOSE) down -v

restart:
	$(COMPOSE) down && $(COMPOSE) up --build -d

logs:
	$(COMPOSE) logs -f

ps:
	$(COMPOSE) ps

# ---- Single-URL production deployment -------------------------------------
# Publishes ONLY the dashboard (the single front-door URL). Backends stay on
# the internal compose network. Override the public port with PUBLIC_PORT.
#   make deploy                 # serve on http://<host>/       (port 80)
#   PUBLIC_PORT=3000 make deploy # serve on http://<host>:3000/
deploy:
	$(COMPOSE_DEPLOY) up --build -d
	@echo "TradePulse is deploying. Open http://localhost:$${PUBLIC_PORT:-80}/ once healthy (make deploy-ps)."

deploy-down:
	$(COMPOSE_DEPLOY) down -v

deploy-logs:
	$(COMPOSE_DEPLOY) logs -f

deploy-ps:
	$(COMPOSE_DEPLOY) ps

# ---- Public deployment (HTTPS via Caddy, internet-reachable) --------------
# Requires infra/.env with DOMAIN, LEDGER_JWT_SECRET, POSTGRES_PASSWORD and the
# LEDGER_AUTH_*_PASSWORD values set (compose refuses to start otherwise).
#   make deploy-public          # serve https://$DOMAIN/ (ports 80+443)
deploy-public:
	$(COMPOSE_PUBLIC) up --build -d
	@echo "TradePulse public stack is deploying. Once healthy, open https://$${DOMAIN}/"

deploy-public-down:
	$(COMPOSE_PUBLIC) down -v

deploy-public-logs:
	$(COMPOSE_PUBLIC) logs -f

deploy-public-ps:
	$(COMPOSE_PUBLIC) ps

# Verify each service builds and tests WITHOUT Docker (native toolchains).
# Useful in restricted/nested environments where the Docker daemon cannot
# extract image layers. Services with a missing toolchain are skipped.
verify-native:
	bash scripts/verify-native.sh

# Same as verify-native, but a missing toolchain counts as a failure.
verify-native-strict:
	STRICT=1 bash scripts/verify-native.sh

# Remove transient build/verification artifacts (not source). Safe to re-run.
clean:
	rm -rf services/risk-engine/.venv-verify services/risk-engine/.pytest_cache
	rm -rf services/dashboard/node_modules services/dashboard/dist
	rm -rf services/ledger-core/target
	rm -f services/market-data/market-data services/gateway/gateway
	find services -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	@echo "clean: removed transient build/verification artifacts"
