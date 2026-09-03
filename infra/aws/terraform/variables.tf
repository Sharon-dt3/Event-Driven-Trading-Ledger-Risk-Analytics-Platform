variable "aws_region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "Name prefix for all resources."
  type        = string
  default     = "tradepulse"
}

variable "repo_url" {
  description = "Git URL the EC2 instance clones the app from."
  type        = string
  default     = "https://github.com/Sharon-dt3/Event-Driven-Trading-Ledger-Risk-Analytics-Platform.git"
}

variable "repo_branch" {
  description = "Branch to check out on the instance."
  type        = string
  default     = "main"
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.0.0.0/16"
}

variable "instance_type" {
  description = "EC2 instance type running the app containers. t3.small (2GB) is recommended; t3.micro can OOM."
  type        = string
  default     = "t3.small"
}

variable "db_name" {
  description = "Postgres database name."
  type        = string
  default     = "tradepulse"
}

variable "db_username" {
  description = "Postgres master username."
  type        = string
  default     = "tradepulse"
}

variable "db_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t3.micro"
}

variable "db_allocated_storage" {
  description = "RDS allocated storage (GiB)."
  type        = number
  default     = 20
}

variable "cache_node_type" {
  description = "ElastiCache node type."
  type        = string
  default     = "cache.t3.micro"
}

variable "ssh_ingress_cidr" {
  description = "CIDR allowed to SSH to the instance (via its private IP / SSM). Set to your IP or leave empty to disable SSH (use SSM Session Manager instead)."
  type        = string
  default     = ""
}

variable "key_pair_name" {
  description = "Optional existing EC2 key pair name for SSH. Leave empty to rely on SSM Session Manager."
  type        = string
  default     = ""
}
