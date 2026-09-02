package com.tradepulse.ledger.ledger;

import static org.assertj.core.api.Assertions.assertThat;

import com.tradepulse.ledger.domain.TradeRequestDto;
import java.math.BigDecimal;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.TestPropertySource;

/**
 * Phase 4 compliance: with a low max-position limit, a trade that would exceed it
 * is rejected with MAX_POSITION_EXCEEDED, still audited, and writes no journal
 * entry. Cash is sufficient here, so NEGATIVE_CASH does not pre-empt the rule.
 */
@SpringBootTest
@TestPropertySource(properties = "ledger.max-position=5")
class MaxPositionComplianceTest {

    @Autowired
    LedgerService ledgerService;

    @Autowired
    JdbcTemplate jdbc;

    @Test
    void postTrade_rejectsMaxPositionExceeded_butAudits() {
        UUID rid = UUID.randomUUID();
        // 10 shares > limit of 5; 10 * $100 = $1000 <= $10,000 seed cash.
        var outcome = ledgerService.postTrade(new TradeRequestDto(
                rid, "acct_123", "AAPL", "BUY",
                BigDecimal.valueOf(10), BigDecimal.valueOf(100.0), "user_42"));

        assertThat(outcome.result().status()).isEqualTo("rejected");
        assertThat(outcome.result().rejection_reason()).isEqualTo("MAX_POSITION_EXCEEDED");

        Integer rejectedAudits = jdbc.queryForObject(
                "SELECT COUNT(*) FROM audit_log WHERE source_event_id = ? AND outcome = 'rejected'",
                Integer.class, rid);
        assertThat(rejectedAudits).isEqualTo(1);

        Integer entries = jdbc.queryForObject(
                "SELECT COUNT(*) FROM journal_entries WHERE source_event_id = ?", Integer.class, rid);
        assertThat(entries).isEqualTo(0);
    }
}
