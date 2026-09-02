package com.tradepulse.ledger.domain;

import java.math.BigDecimal;

/** Current position per instrument (contract: Position). */
public record PositionDto(String account_id, String symbol, BigDecimal quantity, BigDecimal avg_price) {
}
