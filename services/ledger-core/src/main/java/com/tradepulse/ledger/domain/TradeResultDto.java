package com.tradepulse.ledger.domain;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.UUID;

/**
 * Result of a trade submission and the shape returned by the trade-history read
 * endpoint. `status` is 'posted' or 'rejected'; `rejection_reason` is present
 * only when rejected. The descriptive fields (`symbol`, `side`, `quantity`,
 * `price`) echo what was traded so history rows are self-describing.
 */
public record TradeResultDto(
        UUID request_id,
        String journal_entry_id,
        String symbol,
        String side,
        BigDecimal quantity,
        BigDecimal price,
        String status,
        String rejection_reason,
        OffsetDateTime posted_at) {
}
