-- Phase 2 — seed a demo trader + funded account (mirrors the POC's acct_123).

INSERT INTO users (user_id, username, role, created_at)
VALUES ('00000000-0000-0000-0000-000000000001', 'demo_trader', 'trader', CURRENT_TIMESTAMP);

INSERT INTO accounts (account_id, user_id, currency, cash_balance, created_at)
VALUES ('acct_123', '00000000-0000-0000-0000-000000000001', 'USD', 10000.0000, CURRENT_TIMESTAMP);
