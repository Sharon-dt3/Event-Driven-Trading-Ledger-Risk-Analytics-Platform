package com.tradepulse.ledger.ledger;

import static org.assertj.core.api.Assertions.assertThat;

import com.tradepulse.ledger.domain.TradeRequestDto;
import com.tradepulse.ledger.domain.TradeResultDto;
import java.math.BigDecimal;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;

/**
 * Phase 2 acceptance: post a trade and PROVE debits = credits, an audit row is
 * written, and idempotency holds (no double-post). Runs on H2 in PostgreSQL
 * mode via Flyway — no Docker required.
 */
@SpringBootTest
class LedgerServiceTest {

    @Autowired
    LedgerService ledgerService;

    @Autowired
    JdbcTemplate jdbc;

    private TradeRequestDto buy(UUID requestId, double qty, double price) {
        return new TradeRequestDto(requestId, "acct_123", "AAPL", "BUY",
                BigDecimal.valueOf(qty), BigDecimal.valueOf(price), "user_42");
    }

    @Test
    void postTrade_writesBalancedDoubleEntry_andAudit() {
        UUID rid = UUID.randomUUID();
        LedgerService.PostOutcome outcome = ledgerService.postTrade(buy(rid, 10, 100.0));

        assertThat(outcome.created()).isTrue();
        TradeResultDto result = outcome.result();
        assertThat(result.status()).isEqualTo("posted");
        assertThat(result.journal_entry_id()).isNotNull();

        // Debits == Credits for this posting.
        BigDecimal debits = jdbc.queryForObject(
                "SELECT COALESCE(SUM(debit),0) FROM journal_lines WHERE journal_entry_id = ?",
                BigDecimal.class, UUID.fromString(result.journal_entry_id()));
        BigDecimal credits = jdbc.queryForObject(
                "SELECT COALESCE(SUM(credit),0) FROM journal_lines WHERE journal_entry_id = ?",
                BigDecimal.class, UUID.fromString(result.journal_entry_id()));
        assertThat(debits).isEqualByComparingTo(credits);
        assertThat(debits).isEqualByComparingTo(BigDecimal.valueOf(1000.0));

        // Global invariant: all debits == all credits across the whole ledger.
        BigDecimal allD = jdbc.queryForObject("SELECT COALESCE(SUM(debit),0) FROM journal_lines",
                BigDecimal.class);
        BigDecimal allC = jdbc.queryForObject("SELECT COALESCE(SUM(credit),0) FROM journal_lines",
                BigDecimal.class);
        assertThat(allD).isEqualByComparingTo(allC);

        // An audit row was written for this trade.
        Integer audits = jdbc.queryForObject(
                "SELECT COUNT(*) FROM audit_log WHERE source_event_id = ? AND outcome = 'accepted'",
                Integer.class, rid);
        assertThat(audits).isEqualTo(1);

        // An outbox event was staged in the same transaction.
        Integer outbox = jdbc.queryForObject(
                "SELECT COUNT(*) FROM outbox_events WHERE event_type = 'LedgerUpdated'",
                Integer.class);
        assertThat(outbox).isGreaterThanOrEqualTo(1);
    }

    @Test
    void postTrade_isIdempotent_noDoublePost() {
        UUID rid = UUID.randomUUID();
        ledgerService.postTrade(buy(rid, 5, 100.0));
        BigDecimal cashAfterFirst = jdbc.queryForObject(
                "SELECT cash_balance FROM accounts WHERE account_id = 'acct_123'", BigDecimal.class);

        // Same request_id again -> must NOT create a second posting.
        LedgerService.PostOutcome replay = ledgerService.postTrade(buy(rid, 5, 100.0));
        assertThat(replay.created()).isFalse();

        Integer entries = jdbc.queryForObject(
                "SELECT COUNT(*) FROM journal_entries WHERE source_event_id = ?", Integer.class, rid);
        assertThat(entries).isEqualTo(1);

        BigDecimal cashAfterReplay = jdbc.queryForObject(
                "SELECT cash_balance FROM accounts WHERE account_id = 'acct_123'", BigDecimal.class);
        assertThat(cashAfterReplay).isEqualByComparingTo(cashAfterFirst);
    }

    @Test
    void postTrade_rejectsNegativeCash_butAudits() {
        UUID rid = UUID.randomUUID();
        // 1000 shares * $100 = $100,000 >> $10,000 seed cash -> NEGATIVE_CASH.
        LedgerService.PostOutcome outcome = ledgerService.postTrade(buy(rid, 1000, 100.0));

        assertThat(outcome.result().status()).isEqualTo("rejected");
        assertThat(outcome.result().rejection_reason()).isEqualTo("NEGATIVE_CASH");

        Integer rejectedAudits = jdbc.queryForObject(
                "SELECT COUNT(*) FROM audit_log WHERE source_event_id = ? AND outcome = 'rejected'",
                Integer.class, rid);
        assertThat(rejectedAudits).isEqualTo(1);

        // No journal entry for a rejected trade.
        Integer entries = jdbc.queryForObject(
                "SELECT COUNT(*) FROM journal_entries WHERE source_event_id = ?", Integer.class, rid);
        assertThat(entries).isEqualTo(0);
    }
}
