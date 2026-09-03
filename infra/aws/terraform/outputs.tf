output "live_url" {
  description = "Public HTTPS URL (CloudFront) — the single front door."
  value       = "https://${aws_cloudfront_distribution.app.domain_name}/"
}

output "alb_dns_name" {
  description = "Internal ALB DNS (origin behind CloudFront)."
  value       = aws_lb.app.dns_name
}

output "rds_endpoint" {
  description = "RDS PostgreSQL endpoint (private)."
  value       = aws_db_instance.postgres.address
}

output "redis_endpoint" {
  description = "ElastiCache Redis endpoint (private)."
  value       = aws_elasticache_cluster.redis.cache_nodes[0].address
}

output "app_secret_arn" {
  description = "Secrets Manager ARN holding app secrets."
  value       = aws_secretsmanager_secret.app.arn
}

output "ec2_instance_id" {
  description = "App EC2 instance id (connect via SSM Session Manager)."
  value       = aws_instance.app.id
}
