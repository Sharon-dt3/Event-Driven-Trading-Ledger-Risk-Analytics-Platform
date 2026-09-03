# Day 4 — AWS Deployment Runbook (RDS · ElastiCache · EC2 · ALB · CloudFront · Secrets Manager · CloudWatch)

This runbook takes TradePulse to a **live HTTPS URL on the Day-4 AWS
architecture**. Two paths are given:

- **Path A — Terraform (recommended):** `terraform apply` provisions everything.
- **Path B — Manual AWS Console:** the same architecture, built by clicking,
  for when you want to understand each piece or can't use Terraform.

> Both paths stand up **real AWS resources that cost money** while running.
> Tear them down when done (see *Teardown*).

## Architecture: how each Compose service maps to AWS

```
                Internet
                   │  https
            ┌──────▼───────┐
            │  CloudFront  │  (TLS, single front door, caching disabled)
            └──────┬───────┘
                   │  http
            ┌──────▼───────┐
            │     ALB      │  public subnets, health check GET /health
            └──────┬───────┘
                   │
        ┌──────────▼───────────┐   private subnet
        │  EC2 (Docker Compose)│   docker-compose.aws.yml
        │  dashboard :80       │   market-data, ledger-core, risk-engine,
        │  + app containers    │   risk-worker, gateway, dashboard
        └───┬──────────────┬───┘
            │ 5432         │ 6379
     ┌──────▼─────┐  ┌─────▼────────┐
     │ RDS (PG16) │  │ ElastiCache  │
     └────────────┘  │  Redis 7     │
                     └──────────────┘
   Secrets Manager → EC2 user-data → infra/.env
   CloudWatch Logs ← awslogs driver on every container
```

| Local Compose (`docker-compose.deploy.yml`) | AWS-managed equivalent            |
|---------------------------------------------|-----------------------------------|
| `postgres` container                        | **Amazon RDS** PostgreSQL 16      |
| `redis` container                           | **Amazon ElastiCache** Redis 7    |
| app containers (6) on one host              | **EC2** running Docker Compose (`docker-compose.aws.yml`) |
| host port publish                           | **ALB** → EC2 dashboard :80       |
| — (no TLS locally)                          | **CloudFront** (HTTPS front door) |
| in-repo demo secrets / `.env`               | **Secrets Manager** → `.env` at boot |
| `docker logs`                               | **CloudWatch Logs** (awslogs driver) |

The app code is unchanged: `ledger-core` and `risk-engine` already read their
DB/Redis endpoints from env, so pointing them at RDS/ElastiCache is pure config
(see `infra/docker-compose.aws.yml`).

## Path A — Terraform (recommended)

Prereqs: AWS account + credentials configured (`aws configure` or SSO), and
Terraform ≥ 1.5.

```bash
cd infra/aws/terraform
cp terraform.tfvars.example terraform.tfvars   # optional; defaults work
terraform init
terraform apply                                # review the plan, type 'yes'
```

When it finishes (RDS takes several minutes), Terraform prints:

```
live_url = "https://dxxxx.cloudfront.net/"
```

The EC2 instance then clones the repo, pulls secrets, and starts the stack.
CloudFront needs a few minutes to deploy globally, and `ledger-core` ~1–2 min to
go healthy. Then open the `live_url`.

**Login:** usernames `admin` / `demo_trader` / `viewer` / `compliance`. Their
passwords are the random values in Secrets Manager. Retrieve them:

```bash
aws secretsmanager get-secret-value \
  --secret-id "$(terraform output -raw app_secret_arn)" \
  --query SecretString --output text | jq
```

### Watching / debugging

- **App logs:** CloudWatch → Log groups → `/tradepulse/app` (streams per service).
- **Instance shell (no SSH):** AWS Console → EC2 → the instance → *Connect* →
  *Session Manager*, or:
  ```bash
  aws ssm start-session --target "$(terraform output -raw ec2_instance_id)"
  # then: sudo cat /var/log/tradepulse-bootstrap.log
  #       cd /opt/tradepulse && sudo docker compose -f infra/docker-compose.aws.yml ps
  ```

## Path B — Manual AWS Console (same architecture)

Do these in order; each maps to a Terraform file for reference.

1. **VPC** (`network.tf`): VPC `10.0.0.0/16`; 2 public + 2 private subnets across
   2 AZs; Internet Gateway on public; NAT Gateway (in a public subnet) as the
   default route for the private subnets.
2. **Security groups** (`security.tf`): `alb-sg` (inbound 80 from `0.0.0.0/0`);
   `app-sg` (inbound 80 from `alb-sg`, optional 22); `rds-sg` (inbound 5432 from
   `app-sg`); `cache-sg` (inbound 6379 from `app-sg`).
3. **Secrets Manager** (`secrets.tf`): create a secret with JSON keys
   `POSTGRES_PASSWORD`, `LEDGER_JWT_SECRET`, `LEDGER_AUTH_ADMIN_PASSWORD`,
   `LEDGER_AUTH_TRADER_PASSWORD`, `LEDGER_AUTH_VIEWER_PASSWORD`,
   `LEDGER_AUTH_COMPLIANCE_PASSWORD` (use strong random values).
4. **RDS** (`rds.tf`): PostgreSQL 16, `db.t3.micro`, in the private subnet group,
   attached to `rds-sg`, DB name `tradepulse`, user `tradepulse`, password =
   the `POSTGRES_PASSWORD` from step 3. Not publicly accessible.
5. **ElastiCache** (`elasticache.tf`): Redis 7, `cache.t3.micro`, 1 node, private
   subnet group, `cache-sg`.
6. **IAM role** (`iam.tf`): EC2 role allowing `secretsmanager:GetSecretValue` on
   the secret, CloudWatch Logs write, and attach `AmazonSSMManagedInstanceCore`.
7. **CloudWatch** (`cloudwatch.tf`): log group `/tradepulse/app`.
8. **EC2** (`ec2.tf` + `user_data.sh.tftpl`): Amazon Linux 2023, `t3.small`,
   private subnet, `app-sg`, the IAM instance profile, 30 GB gp3. Paste the
   user-data script (substitute the region, secret ARN, RDS/ElastiCache
   endpoints, DB name/user, and log-group name where the template variables are).
9. **ALB** (`alb.tf`): internet-facing, public subnets, `alb-sg`; target group
   (HTTP :80, health check `/health`, expect 200) with the EC2 instance
   registered; listener :80 → forward.
10. **CloudFront** (`cloudfront.tf`): custom origin = ALB DNS, origin protocol
    *HTTP only*; default behavior = *CachingDisabled* + *AllViewer* origin
    request policy, viewer protocol *redirect-to-https*, all methods allowed.
    Use the default `*.cloudfront.net` certificate.

Open `https://<distribution>.cloudfront.net/` once healthy.

## Validation sweep (the six Day-4 criteria)

Run these against the **live CloudFront URL** after the stack is healthy:

1. **No mocks / real data:** log in, place a trade on **Trades**; confirm it
   appears in **Positions**/**P&L** and an entry shows in **Audit** — all served
   from RDS, not fixtures.
2. **Live feed works:** **Ticker** updates and **Risk** recomputes as prices move
   (SSE through CloudFront → ALB → gateway).
3. **Data persists across refresh:** hard-refresh the browser; positions, trades,
   and audit history remain (they live in RDS, not browser state).
4. **Restart-safe (app tier):** on the instance,
   `sudo docker compose -f infra/docker-compose.aws.yml restart`; after services
   come back, prior data is intact and the UI recovers (empty/loading/error
   states render cleanly during the gap).
5. **Kill & restart all containers:** `... down` then `... up -d`; because state
   lives in RDS + ElastiCache (not the containers), nothing is corrupted and the
   ledger's outbox/idempotency prevents double-applied events.
6. **Managed-service recovery:** reboot the EC2 instance (Console → Reboot); the
   Compose stack restarts (`restart: unless-stopped`) and reconnects to the same
   RDS/ElastiCache endpoints — state survives because it was never on the host.

> Note on empty/loading/error states: every screen uses the shared `StateBlock`
> component (`services/dashboard/src/components/StateBlock.jsx`), so during
> restarts the UI shows proper loading/empty/error rather than breaking.

## Teardown (stop the billing)

```bash
cd infra/aws/terraform
terraform destroy
```

Manual path: delete in reverse order (CloudFront → ALB → EC2 → ElastiCache →
RDS → NAT/EIP → secret → log group → VPC). CloudFront takes a while to disable
before it can be deleted.

## Cost & caveats (be honest with yourself)

- **Not free.** RDS, ElastiCache, the NAT Gateway, ALB, and CloudFront all bill
  hourly/for data. A demo run is a few dollars; **leaving it up costs money** —
  destroy it when done.
- **`t3.small` for EC2** is recommended; `t3.micro` (1 GB) can OOM building the
  Java service. If you must use micro, add swap (see git history for the
  free-tier bootstrap) and build sequentially.
- **CloudFront + SSE:** caching is disabled and all headers forwarded so the
  `/stream` feed works; expect a small buffering delay versus hitting the ALB
  directly. For the crispest live feed you can also test against `alb_dns_name`.
- **HTTPS uses the default CloudFront domain.** For a custom domain, add an ACM
  cert (in `us-east-1`) and an `aliases` block to the distribution, plus DNS.

## New AWS accounts: CloudFront must be verified first

Brand-new AWS accounts cannot create CloudFront distributions until AWS verifies
the account (an anti-abuse check). `terraform apply` will fail only on the
CloudFront resource with:
`AccessDenied: Your account must be verified before you can add new CloudFront resources`.
All other resources (RDS, ElastiCache, EC2, ALB, etc.) still succeed.

To handle this, CloudFront is gated behind `enable_cloudfront` (default `false`):

- **Go live now (no CloudFront):** keep the default. `terraform apply` completes
  and `live_url` / `alb_url` give you the ALB HTTP URL. Run the validation sweep
  against that.
- **Add CloudFront later:** open a free AWS Support case asking to enable
  CloudFront; once verified, set `enable_cloudfront = true` in `terraform.tfvars`
  and re-run `terraform apply` — it adds the CDN on top of the existing stack and
  `live_url` switches to the HTTPS CloudFront URL.
