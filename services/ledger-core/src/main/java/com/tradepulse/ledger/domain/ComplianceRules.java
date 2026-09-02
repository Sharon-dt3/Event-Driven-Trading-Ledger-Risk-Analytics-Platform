package com.tradepulse.ledger.domain;

import java.math.BigDecimal;
import java.util.Optional;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * Domain-layer compliance rules for trade posting. Kept separate from the
 * application use-case and persistence so rules can be added/changed in one
 * place (single responsibility; open for extension). Each rule maps to a
 * machine-readable rejection reason from the frozen contract
 * (docs/contracts/openapi/ledger.openapi.yaml -> TradeResult.rejection_reason).
 */
@Component
public class ComplianceRules {

    public static final String NEGATIVE_CASH = "NEGATIVE_CASH";
    public static final String MAX_POSITION_EXCEEDED = "MAX_POSITION_EXCEEDED";

    private final BigDecimal maxPosition;

    public ComplianceRules(@Value("${ledger.max-position:1000000}") BigDecimal maxPosition) {
        this.maxPosition = maxPosition;
    }

    /**
     * Evaluate the rules against the projected post-trade state.
     *
     * @param cashAfter        account cash if the trade were applied
     * @param positionAfter    net position for the symbol if the trade were applied
     * @return the first violated rule's reason, or empty if the trade is compliant
     */
    public Optional<String> firstViolation(BigDecimal cashAfter, BigDecimal positionAfter) {
        if (cashAfter.compareTo(BigDecimal.ZERO) < 0) {
            return Optional.of(NEGATIVE_CASH);
        }
        if (positionAfter.abs().compareTo(maxPosition) > 0) {
            return Optional.of(MAX_POSITION_EXCEEDED);
        }
        return Optional.empty();
    }

    public BigDecimal maxPosition() {
        return maxPosition;
    }
}
