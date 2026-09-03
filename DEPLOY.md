# Deploying TradePulse behind a single URL

TradePulse is already designed to be reached through **one URL**. The dashboard
container runs nginx and reverse-proxies every backend API, so end users only
ever talk to the dashboard's port — never to the individual services.

```
                         ┌─────────────────────────────────────────┐
   http://<host>/  ───▶  │ dashboard (nginx + React SPA, port 3000) │
                         │                                          │
                         │  /            → React SPA (static)       │
                         │  /ledger/...  → ledger-core:8082         │
                         │  /risk/...    → risk-engine:8083         │
                         │  /stream      → gateway:8084 (SSE)       │
                         └──────────────────┬───────────────────────┘
                                            │ internal compose network
        ┌───────────────┬───────────────────┼───────────────┬───────────────┐
    market-data     ledger-core         risk-engine      risk-worker     gateway
     (Go)            (Java/Spring)        (Python)         (Python)        (Go)
        └──────── redis (streams) ───────────┴──────── postgres ──────────┘
```

The proxy rules live in [`services/dashboard/nginx.conf`](services/dashboard/nginx.conf)
(production) and [`services/dashboard/vite.config.js`](services/dashboard/vite.config.js)
(local dev). Because of this, **you do not expose ports 8081–8084 publicly** —
only the dashboard.

## Prerequisites

- A host with a working **Docker daemon** and the Docker Compose plugin.
- Ports: the public port you choose (default **80**) must be free on the host.

> Note: the Go services (`market-data`, `gateway`) and the full stack are built
> and run **inside Docker**, so you do not need Go/Java/Python installed on the
> host — only Docker.

## One-command deploy (single URL)

From the repository root:

```bash
# Serve the whole platform on http://<host>/  (port 80)
make deploy

# Or pick another public port, e.g. 3000:
PUBLIC_PORT=3000 make deploy

# Watch startup until services are healthy:
make deploy-ps
make deploy-logs

# Tear everything down (also removes volumes):
make deploy-down
```

Equivalent raw compose commands (if you prefer not to use make):

```bash
docker compose -f infra/docker-compose.deploy.yml up --build -d
docker compose -f infra/docker-compose.deploy.yml ps
docker compose -f infra/docker-compose.deploy.yml down -v
```

Then open the single URL:

```
http://<host>:${PUBLIC_PORT:-80}/
```

Everything — login, trades, positions, ticker, risk, audit, and the live SSE
feed — is served from that one origin.

## Configuration

Copy `.env.example` to `.env` in `infra/` to override defaults (DB credentials,
symbols, tick interval, log level). The deploy file also honors:

| Variable      | Default | Purpose                                   |
|---------------|---------|-------------------------------------------|
| `PUBLIC_PORT` | `80`    | Host port that serves the single URL      |

`LEDGER_STREAM_ENABLED` defaults to `true` in the deploy file so risk metrics
populate automatically from the ledger event stream.

## Putting it on a real domain (optional TLS)

For a public hostname with HTTPS, keep `PUBLIC_PORT` internal (e.g. 3000) and
put a TLS-terminating reverse proxy in front:

```
Internet ──▶ Caddy/Traefik/Nginx (443, TLS) ──▶ dashboard container (PUBLIC_PORT)
```

Point the proxy's upstream at `http://<host>:${PUBLIC_PORT}` and it will forward
all of `/`, `/ledger`, `/risk`, and `/stream` (SSE) unchanged. Ensure the proxy
does **not** buffer `/stream` so the live feed streams in real time.

## Why not expose each service separately?

You can (the dev compose `infra/docker-compose.yml` does, for debugging), but for
a deployment the single-URL model is simpler and safer: one origin, no CORS, no
per-service DNS, and the backends are not reachable from outside the network.

## Public deployment (HTTPS, anyone on the internet can access)

Use this when you want a shareable public link. It runs the full stack with a
**Caddy** reverse proxy that terminates TLS and is the only exposed service
(ports 80 + 443). Everything else — including the dashboard — stays internal.

### Before you expose it: required hardening

The repo ships **demo credentials and a dev JWT secret in source** (fine for
local use, unsafe on the internet). The public stack therefore **requires**
strong secrets and will refuse to start without them.

1. Point DNS: create an `A` record for your domain (e.g.
   `tradepulse.example.com`) at the host's public IP.
2. Open the firewall / cloud security group for inbound **TCP 80 and 443**
   (80 is needed for the Let's Encrypt HTTP challenge; 443 serves traffic).
3. Create `infra/.env` from `.env.example` and set strong values:

   ```bash
   cd infra
   cp ../.env.example .env
   # then edit .env and set:
   #   DOMAIN=tradepulse.example.com
   #   POSTGRES_PASSWORD=$(openssl rand -base64 24)
   #   LEDGER_JWT_SECRET=$(openssl rand -base64 48)
   #   LEDGER_AUTH_ADMIN_PASSWORD=$(openssl rand -base64 18)
   #   LEDGER_AUTH_TRADER_PASSWORD=...
   #   LEDGER_AUTH_VIEWER_PASSWORD=...
   #   LEDGER_AUTH_COMPLIANCE_PASSWORD=...
   ```

### Deploy

```bash
make deploy-public          # brings up the stack + Caddy (TLS)
make deploy-public-ps       # wait for services to become healthy
make deploy-public-logs     # follow logs (watch Caddy obtain the certificate)
make deploy-public-down     # tear everything down
```

Raw compose equivalent:

```bash
docker compose -f infra/docker-compose.public.yml up --build -d
```

Then open the single public URL:

```
https://<DOMAIN>/
```

Caddy automatically obtains and renews a Let's Encrypt certificate for
`DOMAIN`. The SSE feed (`/stream`) works through Caddy without extra config.

### What "public" means here

- **Network:** anyone on the internet can reach `https://<DOMAIN>/`.
- **Access control:** they land on the login screen. Only accounts whose
  passwords you set in `.env` (admin / demo_trader / viewer / compliance) can
  sign in. The old in-repo demo passwords no longer work once you set your own.
- **Not exposed:** Postgres, Redis, market-data, ledger-core, risk-engine, and
  the gateway have no host ports — only Caddy is published.

### Recommended extra hardening

- Restrict the security group to trusted source IPs if it's not truly for
  everyone.
- Rotate `LEDGER_JWT_SECRET` periodically (invalidates existing sessions).
- Consider a WAF/rate limiting in front for a fully open demo.
- Keep `.env` out of git (it already is via `.gitignore`); never commit real
  secrets.

## Public URL without a domain or cloud VM (Cloudflare Tunnel)

If you just want a link **anyone can open from anywhere** and you're running on
a laptop / home machine behind NAT (no public IP, no domain), use the built-in
**Cloudflare quick tunnel**. A `cloudflared` container makes an outbound
connection to Cloudflare and receives a public HTTPS URL that proxies to your
internal dashboard. No account, no domain, no port-forwarding, no firewall
changes, and TLS is handled by Cloudflare.

### Before sharing: set credentials

The tunnel URL is world-reachable, so change the demo credentials first.
Create `infra/.env` and set strong values (usernames stay
admin / demo_trader / viewer / compliance):

```bash
cd infra && cp ../.env.example .env
# set at least:
#   LEDGER_JWT_SECRET=$(openssl rand -base64 48)
#   LEDGER_AUTH_ADMIN_PASSWORD=...
#   LEDGER_AUTH_TRADER_PASSWORD=...
#   LEDGER_AUTH_VIEWER_PASSWORD=...
#   LEDGER_AUTH_COMPLIANCE_PASSWORD=...
#   POSTGRES_PASSWORD=$(openssl rand -base64 24)
cd ..
```

(You can skip this to try it out, but the public demo passwords in this repo
would then work for anyone who has them.)

### Start the tunnel

```bash
make tunnel        # builds + starts the full stack and the cloudflared tunnel
make tunnel-url    # wait ~20-40s, then prints https://<random>.trycloudflare.com
make tunnel-logs   # follow logs (the URL also appears here)
make tunnel-down   # stop everything
```

Share the printed `https://<random>.trycloudflare.com` URL — anyone on the
internet can open it. The live SSE feed (`/stream`) works through the tunnel.

### Notes / limitations

- The quick-tunnel hostname is **random and temporary** — it changes each time
  you restart `cloudflared`, and Cloudflare rate-limits it. It's ideal for
  demos and sharing, not a permanent production endpoint.
- For a **stable custom domain** over the tunnel, create a named tunnel in a
  (free) Cloudflare account and set a `TUNNEL_TOKEN` instead of the quick
  `--url` mode. Ask and I can wire that up.
- For a classic server deployment with your own domain + Let's Encrypt, use the
  Caddy path above (`make deploy-public`).

## Permanent URL (Named Cloudflare Tunnel)

The quick tunnel above is demo-only: its `https://<random>.trycloudflare.com`
hostname is temporary and changes/expires whenever `cloudflared` restarts, so
you have to keep re-sharing it. For a **permanent URL that always works for
anyone and never breaks**, use a Cloudflare **Named Tunnel**. It still runs from
your laptop behind NAT (outbound-only, no open ports, no public IP), but the
hostname is one you own and it is stable across restarts, reboots, and sleep.

### One-time setup (~10 minutes)

1. Create a free **Cloudflare account** and add a domain (point the domain's
   nameservers at Cloudflare). Any domain works — one you own, a cheap new one,
   or one bought through Cloudflare Registrar.
2. Go to **Cloudflare Zero Trust → Networks → Tunnels → Create a tunnel**,
   choose **Cloudflared**, name it (e.g. `tradepulse`), and copy the **token**
   it shows (a long `eyJ...` string).
3. On that tunnel, add a **Public Hostname**:
   - **Subdomain/Domain:** e.g. `tradepulse.yourdomain.com`
   - **Service:** `HTTP` → `dashboard:3000`
   (The dashboard's nginx already routes `/ledger`, `/risk`, and `/stream`.)
4. Create `infra/.env` and set the token plus strong app secrets:
   ```bash
   cd infra && cp ../.env.example .env
   # then set:
   #   TUNNEL_TOKEN=eyJ...                                  (from step 2)
   #   LEDGER_JWT_SECRET=$(openssl rand -base64 48)
   #   LEDGER_AUTH_ADMIN_PASSWORD=...
   #   LEDGER_AUTH_TRADER_PASSWORD=...
   #   LEDGER_AUTH_VIEWER_PASSWORD=...
   #   LEDGER_AUTH_COMPLIANCE_PASSWORD=...
   #   POSTGRES_PASSWORD=$(openssl rand -base64 24)
   cd ..
   ```

### Run it

```bash
make tunnel-named          # builds + starts the full stack and the named tunnel
make tunnel-named-logs     # wait for "Registered tunnel connection" in cloudflared
make tunnel-named-down     # stop everything
```

Then open your **fixed** URL — e.g. `https://tradepulse.yourdomain.com/`. It is
the same link every time; there is nothing to renew. Share it with anyone.

### Notes

- Uses `infra/docker-compose.named-tunnel.yml`. The public-hostname → service
  mapping lives in the Cloudflare dashboard, so no `--url` flag is used.
- Because the tunnel is token-authenticated and Cloudflare-managed, the URL
  survives `cloudflared` restarts (the failure mode you hit with the quick
  tunnel cannot happen here).
- If you'd rather host on a VM with your own domain + Let's Encrypt instead of a
  tunnel, use the Caddy path (`make deploy-public`).

## Permanent free URL (ngrok static domain)

Want a permanent URL that always works for anyone, costs **nothing**, and needs
**no domain of your own**? Use ngrok's free **static domain**. The free tier
includes one reserved domain (e.g. `your-name.ngrok-free.app`) that is yours
permanently and does not change between restarts — unlike the Cloudflare quick
tunnel (`make tunnel`). The ngrok agent runs from your laptop behind NAT
(outbound-only: no open ports, no public IP, no firewall changes).

### One-time setup (~5 minutes, $0)

1. Create a free ngrok account: https://dashboard.ngrok.com/signup
2. Copy your **authtoken**:
   https://dashboard.ngrok.com/get-started/your-authtoken
3. Claim your free **static domain** (Domains → Create Domain):
   https://dashboard.ngrok.com/domains — it looks like
   `your-name.ngrok-free.app`.
4. Create `infra/.env` and set the token, domain, and strong app secrets:
   ```bash
   cd infra && cp ../.env.example .env
   # then set:
   #   NGROK_AUTHTOKEN=2ab...                       (from step 2)
   #   NGROK_DOMAIN=your-name.ngrok-free.app        (from step 3)
   #   LEDGER_JWT_SECRET=$(openssl rand -base64 48)
   #   LEDGER_AUTH_ADMIN_PASSWORD=...
   #   LEDGER_AUTH_TRADER_PASSWORD=...
   #   LEDGER_AUTH_VIEWER_PASSWORD=...
   #   LEDGER_AUTH_COMPLIANCE_PASSWORD=...
   #   POSTGRES_PASSWORD=$(openssl rand -base64 24)
   cd ..
   ```

### Run it

```bash
make ngrok          # builds + starts the full stack and the ngrok agent
make ngrok-logs     # wait for "started tunnel" in the ngrok logs
make ngrok-down     # stop everything
```

Then open your **fixed** URL — e.g. `https://your-name.ngrok-free.app/`. It is
the same link every time; there is nothing to renew. Share it with anyone.

### Notes

- Uses `infra/docker-compose.ngrok.yml`; ngrok proxies your static domain to the
  internal `dashboard:3000` (which already routes `/ledger`, `/risk`, `/stream`).
- Free-tier caveats: first-time visitors see a brief ngrok interstitial page,
  and there are soft bandwidth/rate limits — fine for demos and sharing. These
  are removed on ngrok paid plans, but you do not need to pay.
- The live SSE feed (`/stream`) works through ngrok without extra config.
```
