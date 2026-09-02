-- Phase 2 — trades (trade requests and their outcome).

CREATE TABLE trades (
    trade_id         UUID PRIMARY KEY,
    request_id       UUID NOT NULL UNIQUE,           -- client idempotency key
    account_id       VARCHAR(64) NOT NULL REFERENCES accounts(account_id),
    symbol           VARCHAR(32) NOT NULL,
    side             VARCHAR(4)  NOT NULL,
    quantity         NUMERIC(20, 4) NOT NULL,
    price            NUMERIC(20, 4) NOT NULL,
    status           VARCHAR(16) NOT NULL,
    rejection_reason VARCHAR(32),
    created_at       TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT chk_trades_side     CHECK (side IN ('BUY', 'SELL')),
    CONSTRAINT chk_trades_status   CHECK (status IN ('posted', 'rejected')),
    CONSTRAINT chk_trades_qty_pos   CHECK (quantity > 0),
    CONSTRAINT chk_trades_price_pos CHECK (price > 0)
);

-- Performance indexes (lookups by account, instrument, and time).
CREATE INDEX idx_trades_account_id ON trades(account_id);
CREATE INDEX idx_trades_symbol     ON trades(symbol);
CREATE INDEX idx_trades_created_at ON trades(created_at);
