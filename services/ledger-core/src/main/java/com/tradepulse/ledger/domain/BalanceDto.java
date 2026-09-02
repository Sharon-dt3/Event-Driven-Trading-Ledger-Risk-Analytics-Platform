package com.tradepulse.ledger.domain;

import java.math.BigDecimal;

/** Cash balance for an account (contract: Balance). */
public record BalanceDto(String account_id, String currency, BigDecimal amount) {
}
