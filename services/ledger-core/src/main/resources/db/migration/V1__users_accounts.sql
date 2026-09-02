-- Phase 2 — users & accounts.
-- Portable SQL (works on PostgreSQL and H2 in PostgreSQL mode).

CREATE TABLE users (
    user_id    UUID PRIMARY KEY,
    username   VARCHAR(100) NOT NULL UNIQUE,
    role       VARCHAR(20)  NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT chk_users_role CHECK (role IN ('viewer', 'trader', 'compliance', 'admin'))
);

CREATE TABLE accounts (
    account_id   VARCHAR(64) PRIMARY KEY,
    user_id      UUID NOT NULL REFERENCES users(user_id),
    currency     VARCHAR(3)     NOT NULL DEFAULT 'USD',
    cash_balance NUMERIC(20, 4) NOT NULL DEFAULT 0,
    created_at   TIMESTAMP WITH TIME ZONE NOT NULL,
    -- Money invariant: an account can never hold negative cash.
    CONSTRAINT chk_accounts_cash_non_negative CHECK (cash_balance >= 0)
);

CREATE INDEX idx_accounts_user_id ON accounts(user_id);
