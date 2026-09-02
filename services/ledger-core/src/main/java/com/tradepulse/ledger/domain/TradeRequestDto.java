package com.tradepulse.ledger.domain;

import java.math.BigDecimal;
import java.util.UUID;

/**
 * Trade submission payload for POST /trades. Field names mirror the frozen
 * contract (docs/contracts/openapi/ledger.openapi.yaml -> TradeRequest and
 * events/trade_requested.v1).
 */
public record TradeRequestDto(
        UUID request_id,
        String account_id,
        String symbol,
        String side,
        BigDecimal quantity,
        BigDecimal price,
        String requested_by) {
}
