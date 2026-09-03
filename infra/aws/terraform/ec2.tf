data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }
  filter {
    name   = "architecture"
    values = ["x86_64"]
  }
}

locals {
  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    aws_region     = var.aws_region
    repo_url       = var.repo_url
    repo_branch    = var.repo_branch
    secret_arn     = aws_secretsmanager_secret.app.arn
    rds_host       = aws_db_instance.postgres.address
    redis_host     = aws_elasticache_cluster.redis.cache_nodes[0].address
    db_name        = var.db_name
    db_username    = var.db_username
    cw_log_group   = aws_cloudwatch_log_group.app.name
  })
}

resource "aws_instance" "app" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.private[0].id
  vpc_security_group_ids = [aws_security_group.app.id]
  iam_instance_profile   = aws_iam_instance_profile.app.name
  key_name               = var.key_pair_name == "" ? null : var.key_pair_name
  user_data              = local.user_data

  root_block_device {
    volume_size = 30
    volume_type = "gp3"
  }

  tags = { Name = "${var.project}-app" }

  depends_on = [
    aws_db_instance.postgres,
    aws_elasticache_cluster.redis,
    aws_nat_gateway.nat,
  ]
}
