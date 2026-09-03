package com.tradepulse.ledger.domain;

import java.math.BigDecimal;

/**
 * Payload for the admin-only cash credit endpoint
 * (POST /admin/accounts/{accountId}/credit). {@code amount} must be &gt; 0;
 * {@code reason} is a free-text note recorded in the audit log.
 */
public record AdminCreditRequest(BigDecimal amount, String reason) {
}
