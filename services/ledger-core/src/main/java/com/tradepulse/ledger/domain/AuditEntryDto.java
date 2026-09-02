package com.tradepulse.ledger.domain;

import java.time.OffsetDateTime;

/** Immutable audit log entry (contract: AuditEntry). */
public record AuditEntryDto(
        String audit_id,
        String account_id,
        String action,
        String outcome,
        String reason,
        OffsetDateTime recorded_at) {
}
