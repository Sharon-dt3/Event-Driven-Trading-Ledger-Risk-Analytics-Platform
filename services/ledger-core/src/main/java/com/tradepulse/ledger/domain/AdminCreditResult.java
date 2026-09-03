package com.tradepulse.ledger.domain;

import java.math.BigDecimal;

/**
 * Outcome of an admin cash credit: the account, the amount added, the resulting
 * cash balance, and a status string ("credited").
 */
public record AdminCreditResult(
        String account_id,
        BigDecimal amount,
        BigDecimal new_cash_balance,
        String status) {
}
