# Deploying TradePulse on AWS Free Tier (EC2 `t3.micro`, ~$0)

This guide runs the **entire** TradePulse stack on a single AWS Free Tier EC2
instance for **$0** during the first 12 months (750 hrs/month of `t3.micro`).

> ⚠️ **Reality check.** TradePulse is 8 containers, including a Java/Spring
> service (`ledger-core`) that is memory-hungry to build and run. A `t3.micro`
> has only **1 GB of RAM**, so the naive `make deploy` will run out of memory.
> This guide works around that with **swap** + a **sequential image build**.
> It is best-effort: expect slow builds and treat it as a demo/eval box, not a
> production tier. If you want headroom, a paid `t3.small` (2 GB) runs the same
> steps without the OOM risk — see [`DEPLOY.md`](../DEPLOY.md).

## What you get

- The whole platform behind **one URL**: `http://<EC2-public-IP>/`
  (the dashboard's nginx reverse-proxies `/ledger`, `/risk`, and `/stream`).
- Strong, auto-generated login secrets (the in-repo demo passwords are
  replaced).
- No domain required. (Plain HTTP on the public IP. For HTTPS you'd need a
  domain — see the Caddy path in `DEPLOY.md`, or front it with a tunnel.)

## The two OOM mitigations (why this works on 1 GB)

1. **A 4 GB swapfile.** Gives the kernel spillover room so the Java build and
   Postgres don't get killed under memory pressure.
2. **Sequential Docker builds.** Docker Compose builds images in *parallel* by
   default; on a `t3.micro` that is what actually OOM-kills the build. The
   bootstrap script builds them one at a time instead.

Both are handled automatically by
[`scripts/aws-ec2-bootstrap.sh`](../scripts/aws-ec2-bootstrap.sh).

## Step 1 — Launch the instance

1. EC2 → **Launch instance**.
2. **AMI:** Amazon Linux 2023 *or* Ubuntu 22.04/24.04 (both supported).
3. **Instance type:** `t3.micro` (Free Tier eligible in most regions; if your
   region only offers `t2.micro` for free, that works too).
4. **Key pair:** create/select one so you can SSH in.
5. **Storage:** bump the root EBS volume to **30 GB gp3** (still within the
   30 GB Free Tier allowance). Docker images for 5 built services need the room.
6. **Security group — inbound rules:**
   | Type       | Port | Source        | Why                          |
   |------------|------|---------------|------------------------------|
   | SSH        | 22   | *your IP*     | admin access                 |
   | HTTP       | 80   | `0.0.0.0/0`   | the single public app URL    |

   Do **not** open 8081–8084 — those services stay on the internal network.

## Step 2 — Bootstrap (choose ONE)

### Option 2a — Automatic (EC2 user-data)

When launching, expand **Advanced details → User data** and paste the entire
contents of [`scripts/aws-ec2-bootstrap.sh`](../scripts/aws-ec2-bootstrap.sh).
It runs as root on first boot: installs Docker, adds swap, clones the repo,
generates `infra/.env`, and builds + starts the stack.

Track it after the instance boots:

```bash
sudo tail -f /var/log/cloud-init-output.log
```

### Option 2b — Manual (SSH in and run it)

```bash
ssh -i <your-key>.pem ec2-user@<EC2-public-IP>     # 'ubuntu@' on Ubuntu AMIs

# fetch and run the bootstrap (installs Docker, swap, builds, starts):
curl -fsSL \
  https://raw.githubusercontent.com/Sharon-dt3/Event-Driven-Trading-Ledger-Risk-Analytics-Platform/main/scripts/aws-ec2-bootstrap.sh \
  -o bootstrap.sh
sudo bash bootstrap.sh
```

Useful overrides (export before running): `SWAP_GB`, `PUBLIC_PORT`,
`REPO_BRANCH`, `APP_DIR`. Example: `SWAP_GB=6 sudo -E bash bootstrap.sh`.

## Step 3 — Wait, then open the URL

The `ledger-core` Java service takes ~1–2 minutes to become healthy after its
image builds. Watch the stack:

```bash
cd /opt/tradepulse
docker compose -f infra/docker-compose.deploy.yml ps
docker compose -f infra/docker-compose.deploy.yml logs -f
```

When the dashboard is healthy, open:

```
http://<EC2-public-IP>/
```

Log in with username `admin` (or `demo_trader` / `viewer` / `compliance`) and
the password the script printed and saved in `/opt/tradepulse/infra/.env`.

## Operating it

```bash
cd /opt/tradepulse
# stop everything (keeps data volumes):
docker compose -f infra/docker-compose.deploy.yml stop
# start again:
docker compose -f infra/docker-compose.deploy.yml start
# full teardown incl. volumes:
docker compose -f infra/docker-compose.deploy.yml down -v
```

## Troubleshooting

- **A container was `Killed` / exits during build or startup.** That's OOM.
  Confirm swap is active (`free -h` should show a Swap line). If it's still
  tight, re-run the bootstrap with a bigger swapfile: `SWAP_GB=6 sudo -E bash
  bootstrap.sh`, or stop/rebuild one service at a time.
- **Build is extremely slow.** Expected on `t3.micro` (2 vCPU burst, limited
  CPU credits). The first build is the slow one; subsequent `up` calls reuse
  cached layers. If you hit CPU-credit throttling, let it idle a few minutes or
  switch to `t3.small`.
- **Can't reach the URL.** Check the security group allows inbound **80** from
  your network, and that `docker compose ps` shows `dashboard` healthy.
- **Ran out of disk.** Increase the EBS volume, or run
  `docker system prune -af` to reclaim space from intermediate build layers.

## Cost notes

- `t3.micro` (or `t2.micro`) is Free Tier for **750 hrs/month for 12 months** on
  a new account — enough to run one instance continuously.
- Watch **EBS storage** (30 GB free), **data transfer out** (100 GB/month free),
  and remember the free window ends after 12 months. **Stop or terminate** the
  instance when you're done to avoid charges.

## When to graduate off free tier

If the OOM tuning gets annoying or you want HTTPS on a real domain, move to the
`t3.small` + Caddy path in [`DEPLOY.md`](../DEPLOY.md) (`make deploy-public`).
It's the same repo, no code changes — just more RAM and automatic TLS.
