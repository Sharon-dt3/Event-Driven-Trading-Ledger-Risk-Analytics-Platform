# ALB: accepts HTTP/HTTPS from the internet (CloudFront in front). For a tighter
# setup, restrict to CloudFront's managed prefix list; kept open here for clarity.
resource "aws_security_group" "alb" {
  name_prefix = "${var.project}-alb-"
  description = "ALB ingress"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTP from internet/CloudFront"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project}-alb-sg" }
}

# EC2 app host: only the ALB may reach the dashboard port (80). Optional SSH.
resource "aws_security_group" "app" {
  name_prefix = "${var.project}-app-"
  description = "App EC2 ingress"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Dashboard from ALB"
    from_port       = 80
    to_port         = 80
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  dynamic "ingress" {
    for_each = var.ssh_ingress_cidr == "" ? [] : [var.ssh_ingress_cidr]
    content {
      description = "SSH"
      from_port   = 22
      to_port     = 22
      protocol    = "tcp"
      cidr_blocks = [ingress.value]
    }
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project}-app-sg" }
}

# RDS: only the app host may connect on 5432.
resource "aws_security_group" "rds" {
  name_prefix = "${var.project}-rds-"
  description = "RDS ingress from app"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Postgres from app"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project}-rds-sg" }
}

# ElastiCache: only the app host may connect on 6379.
resource "aws_security_group" "cache" {
  name_prefix = "${var.project}-cache-"
  description = "ElastiCache ingress from app"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Redis from app"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project}-cache-sg" }
}
