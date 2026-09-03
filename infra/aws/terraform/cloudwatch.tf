resource "aws_cloudwatch_log_group" "app" {
  name              = "/${var.project}/app"
  retention_in_days = 14
  tags              = { Name = "${var.project}-logs" }
}
