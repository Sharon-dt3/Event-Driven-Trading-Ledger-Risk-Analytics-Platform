COMPOSE = docker compose -f infra/docker-compose.yml
COMPOSE_DEPLOY = docker compose -f infra/docker-compose.deploy.yml
COMPOSE_PUBLIC = docker compose -f infra/docker-compose.public.yml
COMPOSE_TUNNEL = docker compose -f infra/docker-compose.tunnel.yml
COMPOSE_TUNNEL_NAMED = docker compose -f infra/docker-compose.named-tunnel.yml
COMPOSE_NGROK = docker compose -f infra/docker-compose.ngrok.yml

.PHONY: up down logs ps build restart deploy deploy-down deploy-logs deploy-ps deploy-public deploy-public-down deploy-public-logs deploy-public-ps tunnel tunnel-url tunnel-down tunnel-logs tunnel-ps tunnel-named tunnel-named-down tunnel-named-logs tunnel-named-ps ngrok ngrok-down ngrok-logs ngrok-ps verify-native verify-native-strict clean

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

# ---- Public deployment via Cloudflare Tunnel (no domain / public IP) ------
# Easiest way to let anyone on the internet reach the app from a laptop behind
# NAT. Brings up the full stack + a cloudflared quick tunnel, then prints the
# public https://<random>.trycloudflare.com URL.
#   make tunnel        # start the stack + tunnel
#   make tunnel-url    # print the public URL (wait ~20-40s after `make tunnel`)
tunnel:
	$(COMPOSE_TUNNEL) up --build -d
	@echo "Tunnel starting. In ~20-40s run 'make tunnel-url' to get your public https URL."

tunnel-url:
	@$(COMPOSE_TUNNEL) logs cloudflared 2>/dev/null | grep -oE 'https://[a-zA-Z0-9-]+\.trycloudflare\.com' | tail -1 \
		|| echo "URL not ready yet — wait a few seconds and re-run 'make tunnel-url' (or check 'make tunnel-logs')."

tunnel-down:
	$(COMPOSE_TUNNEL) down -v

tunnel-logs:
	$(COMPOSE_TUNNEL) logs -f

tunnel-ps:
	$(COMPOSE_TUNNEL) ps

# ---- PERMANENT public URL via a Cloudflare NAMED Tunnel -------------------
# Fixed hostname you own (e.g. https://tradepulse.yourdomain.com) that never
# changes or expires — unlike `make tunnel` (quick tunnel). Requires a free
# Cloudflare account, a domain on Cloudflare, and TUNNEL_TOKEN in infra/.env.
# See DEPLOY.md "Permanent URL (Named Cloudflare Tunnel)" for the 1-time setup.
#   make tunnel-named        # start the stack + named tunnel
#   make tunnel-named-logs   # watch for "Registered tunnel connection"
tunnel-named:
	$(COMPOSE_TUNNEL_NAMED) up --build -d
	@echo "Named tunnel starting. Open your fixed https://<your-hostname>/ once cloudflared connects (make tunnel-named-logs)."

tunnel-named-down:
	$(COMPOSE_TUNNEL_NAMED) down -v

tunnel-named-logs:
	$(COMPOSE_TUNNEL_NAMED) logs -f

tunnel-named-ps:
	$(COMPOSE_TUNNEL_NAMED) ps

# ---- PERMANENT FREE public URL via ngrok static domain --------------------
# Fixed https://<your-name>.ngrok-free.app URL that never changes — FREE and
# needs NO domain of your own. Requires NGROK_AUTHTOKEN + NGROK_DOMAIN in
# infra/.env (create a free ngrok account, then claim one static domain).
# See DEPLOY.md "Permanent free URL (ngrok static domain)" for the 1-time setup.
#   make ngrok        # start the stack + ngrok on your fixed URL
#   make ngrok-logs   # watch for "started tunnel"
ngrok:
	$(COMPOSE_NGROK) up --build -d
	@echo "ngrok starting. Open your fixed https://$${NGROK_DOMAIN}/ once the agent connects (make ngrok-logs)."

ngrok-down:
	$(COMPOSE_NGROK) down -v

ngrok-logs:
	$(COMPOSE_NGROK) logs -f

ngrok-ps:
	$(COMPOSE_NGROK) ps

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
