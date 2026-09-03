resource "random_password" "db" {
  length  = 24
  special = false
}

resource "random_password" "jwt" {
  length  = 48
  special = false
}

resource "random_password" "admin" {
  length  = 18
  special = false
}

resource "random_password" "trader" {
  length  = 18
  special = false
}

resource "random_password" "viewer" {
  length  = 18
  special = false
}

resource "random_password" "compliance" {
  length  = 18
  special = false
}

# One JSON secret with everything the app needs. The EC2 user-data reads it at
# boot and writes infra/.env. Rotate by updating this secret and recycling EC2.
resource "aws_secretsmanager_secret" "app" {
  name_prefix = "${var.project}/app-"
  description = "TradePulse application secrets (DB password, JWT, role passwords)."
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id
  secret_string = jsonencode({
    POSTGRES_PASSWORD               = random_password.db.result
    LEDGER_JWT_SECRET               = random_password.jwt.result
    LEDGER_AUTH_ADMIN_PASSWORD      = random_password.admin.result
    LEDGER_AUTH_TRADER_PASSWORD     = random_password.trader.result
    LEDGER_AUTH_VIEWER_PASSWORD     = random_password.viewer.result
    LEDGER_AUTH_COMPLIANCE_PASSWORD = random_password.compliance.result
  })
}
