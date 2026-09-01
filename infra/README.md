# infra

Deployment and local orchestration.

- Local: Docker Compose (PostgreSQL, Redis, and the services).
- AWS (Phase 10): ECS Fargate, ALB (`/ledger`, `/risk`, `/ws`), RDS PostgreSQL,
  ElastiCache Redis, S3 + CloudFront, Secrets Manager/SSM, CloudWatch, ECR CI/CD.
- Status: Phase 0 placeholder (implemented in a later phase).
