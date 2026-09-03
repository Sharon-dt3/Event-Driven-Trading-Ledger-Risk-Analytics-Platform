# infra

Deployment and local orchestration.

- Local: Docker Compose (PostgreSQL, Redis, and the services).
- AWS (Day 4): EC2 + Docker Compose behind an ALB and CloudFront, with RDS
  PostgreSQL, ElastiCache Redis, Secrets Manager, and CloudWatch Logs.
  Terraform lives in `infra/aws/terraform/`; the AWS Compose file is
  `infra/docker-compose.aws.yml`.
- Deploy guide: `docs/aws-day4-runbook.md` (Terraform path + manual-console
  path + the six-point validation sweep).
