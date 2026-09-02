package com.tradepulse.ledger.domain;

import java.time.OffsetDateTime;
import java.util.UUID;

/**
 * Result of a trade submission. `status` is 'posted' or 'rejected';
 * `rejection_reason` is present only when rejected.
 */
public record TradeResultDto(
        UUID request_id,
        String journal_entry_id,
        String status,
        String rejection_reason,
        OffsetDateTime posted_at) {
}
