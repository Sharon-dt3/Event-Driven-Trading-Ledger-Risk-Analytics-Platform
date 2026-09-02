-- TradePulse local Postgres bootstrap.
-- The database itself is created by the postgres image via POSTGRES_DB.
-- Schema/tables are introduced in later phases (ledger-core migrations).

CREATE EXTENSION IF NOT EXISTS "pgcrypto";
