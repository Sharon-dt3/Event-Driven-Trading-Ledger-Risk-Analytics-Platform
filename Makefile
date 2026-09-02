COMPOSE = docker compose -f infra/docker-compose.yml

.PHONY: up down logs ps build restart verify-native verify-native-strict clean

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
