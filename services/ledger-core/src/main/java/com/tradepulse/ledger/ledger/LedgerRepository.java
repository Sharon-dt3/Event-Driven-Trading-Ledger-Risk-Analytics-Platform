package com.tradepulse.ledger.ledger;

import com.tradepulse.ledger.domain.AuditEntryDto;
import com.tradepulse.ledger.domain.BalanceDto;
import com.tradepulse.ledger.domain.TradeResultDto;
import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

/**
 * All SQL for the ledger system-of-record. Kept as explicit JdbcTemplate calls
 * so the invariants (double-entry, idempotency) are transparent and auditable.
 */
@Repository
public class LedgerRepository {

    private final JdbcTemplate jdbc;

    public LedgerRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    // --- idempotency / reads used during posting ---

    public Optional<TradeResultDto> findTradeByRequestId(UUID requestId) {
        List<TradeResultDto> rows = jdbc.query(
                "SELECT t.request_id, je.journal_entry_id, t.status, t.rejection_reason, je.posted_at "
                        + "FROM trades t "
                        + "LEFT JOIN journal_entries je ON je.source_event_id = t.request_id "
                        + "WHERE t.request_id = ?",
                tradeResultMapper(), requestId);
        return rows.isEmpty() ? Optional.empty() : Optional.of(rows.get(0));
    }

    /** Returns the account's cash, or null if the account does not exist. */
    public BigDecimal getCash(String accountId) {
        List<BigDecimal> r = jdbc.query(
                "SELECT cash_balance FROM accounts WHERE account_id = ?",
                (rs, i) -> rs.getBigDecimal(1), accountId);
        return r.isEmpty() ? null : r.get(0);
    }

    /** Net position (BUY +qty, SELL -qty) across posted trades for account+symbol. */
    public BigDecimal positionAfter(String accountId, String symbol) {
        BigDecimal p = jdbc.queryForObject(
                "SELECT COALESCE(SUM(CASE WHEN side = 'BUY' THEN quantity ELSE -quantity END), 0) "
                        + "FROM trades WHERE account_id = ? AND symbol = ? AND status = 'posted'",
                BigDecimal.class, accountId, symbol);
        return p == null ? BigDecimal.ZERO : p;
    }

    // --- writes (all invoked inside a single transaction by LedgerService) ---

    public void insertTrade(UUID tradeId, UUID requestId, String accountId, String symbol,
                            String side, BigDecimal quantity, BigDecimal price, String status,
                            String rejectionReason, OffsetDateTime createdAt) {
        jdbc.update(
                "INSERT INTO trades(trade_id, request_id, account_id, symbol, side, quantity, price, "
                        + "status, rejection_reason, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                tradeId, requestId, accountId, symbol, side, quantity, price, status,
                rejectionReason, createdAt);
    }

    public void insertJournalEntry(UUID journalEntryId, UUID sourceEventId, String accountId,
                                   OffsetDateTime postedAt) {
        jdbc.update(
                "INSERT INTO journal_entries(journal_entry_id, source_event_id, account_id, posted_at) "
                        + "VALUES (?,?,?,?)",
                journalEntryId, sourceEventId, accountId, postedAt);
    }

    public void insertJournalLine(UUID journalEntryId, String accountRef, BigDecimal debit,
                                  BigDecimal credit) {
        jdbc.update(
                "INSERT INTO journal_lines(journal_entry_id, account_ref, debit, credit) VALUES (?,?,?,?)",
                journalEntryId, accountRef, debit, credit);
    }

    public void updateCash(String accountId, BigDecimal delta) {
        jdbc.update("UPDATE accounts SET cash_balance = cash_balance + ? WHERE account_id = ?",
                delta, accountId);
    }

    public void insertAudit(UUID auditId, String accountId, UUID sourceEventId, String action,
                            String outcome, String reason, OffsetDateTime recordedAt) {
        jdbc.update(
                "INSERT INTO audit_log(audit_id, account_id, source_event_id, action, outcome, reason, "
                        + "recorded_at) VALUES (?,?,?,?,?,?,?)",
                auditId, accountId, sourceEventId, action, outcome, reason, recordedAt);
    }

    public void insertOutbox(UUID eventId, String eventType, String payload, OffsetDateTime createdAt) {
        jdbc.update(
                "INSERT INTO outbox_events(event_id, event_type, payload, sent, created_at) "
                        + "VALUES (?,?,?,?,?)",
                eventId, eventType, payload, Boolean.FALSE, createdAt);
    }

    // --- read endpoints ---

    public List<TradeResultDto> history(String accountId, String status) {
        StringBuilder sql = new StringBuilder(
                "SELECT t.request_id, je.journal_entry_id, t.status, t.rejection_reason, je.posted_at "
                        + "FROM trades t "
                        + "LEFT JOIN journal_entries je ON je.source_event_id = t.request_id WHERE 1=1");
        List<Object> args = new ArrayList<>();
        if (accountId != null) {
            sql.append(" AND t.account_id = ?");
            args.add(accountId);
        }
        if (status != null) {
            sql.append(" AND t.status = ?");
            args.add(status);
        }
        sql.append(" ORDER BY t.created_at");
        return jdbc.query(sql.toString(), tradeResultMapper(), args.toArray());
    }

    public List<BalanceDto> balances(String accountId) {
        StringBuilder sql = new StringBuilder(
                "SELECT account_id, currency, cash_balance FROM accounts WHERE 1=1");
        List<Object> args = new ArrayList<>();
        if (accountId != null) {
            sql.append(" AND account_id = ?");
            args.add(accountId);
        }
        return jdbc.query(sql.toString(),
                (rs, i) -> new BalanceDto(rs.getString("account_id"), rs.getString("currency"),
                        rs.getBigDecimal("cash_balance")),
                args.toArray());
    }

    public List<AuditEntryDto> audit(String accountId) {
        StringBuilder sql = new StringBuilder(
                "SELECT audit_id, account_id, action, outcome, reason, recorded_at FROM audit_log WHERE 1=1");
        List<Object> args = new ArrayList<>();
        if (accountId != null) {
            sql.append(" AND account_id = ?");
            args.add(accountId);
        }
        sql.append(" ORDER BY recorded_at");
        return jdbc.query(sql.toString(),
                (rs, i) -> new AuditEntryDto(
                        rs.getString("audit_id"),
                        rs.getString("account_id"),
                        rs.getString("action"),
                        rs.getString("outcome"),
                        rs.getString("reason"),
                        rs.getObject("recorded_at", OffsetDateTime.class)),
                args.toArray());
    }

    private RowMapper<TradeResultDto> tradeResultMapper() {
        return (rs, i) -> {
            String je = rs.getString("journal_entry_id");
            return new TradeResultDto(
                    UUID.fromString(rs.getString("request_id")),
                    je,
                    rs.getString("status"),
                    rs.getString("rejection_reason"),
                    rs.getObject("posted_at", OffsetDateTime.class));
        };
    }
}
