-- Phase 2 — audit log (compliance) and transactional outbox.

CREATE TABLE audit_log (
    audit_id        UUID PRIMARY KEY,
    account_id      VARCHAR(64),
    source_event_id UUID,
    action          VARCHAR(32) NOT NULL,
    outcome         VARCHAR(16) NOT NULL,
    reason          VARCHAR(64),
    recorded_at     TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT chk_audit_outcome CHECK (outcome IN ('accepted', 'rejected'))
);

CREATE INDEX idx_audit_account_id  ON audit_log(account_id);
CREATE INDEX idx_audit_recorded_at ON audit_log(recorded_at);

CREATE TABLE outbox_events (
    event_id   UUID PRIMARY KEY,
    event_type VARCHAR(64) NOT NULL,
    payload    TEXT NOT NULL,                        -- serialized event envelope (JSON)
    sent       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL
);

-- The relay scans unsent rows oldest-first.
CREATE INDEX idx_outbox_unsent ON outbox_events(sent, created_at);
