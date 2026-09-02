package com.tradepulse.ledger.ledger;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.tradepulse.ledger.domain.ComplianceRules;
import com.tradepulse.ledger.domain.TradeRequestDto;
import com.tradepulse.ledger.domain.TradeResultDto;
import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import org.slf4j.MDC;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * Application/use-case layer for trade posting. Every accepted trade writes, in
 * ONE transaction: the trade row, a balanced double-entry journal (entry + two
 * mirrored lines), the cash update, an audit row, and an outbox event — so
 * effects are atomic. Idempotent by request_id; rejections are still audited.
 *
 * Compliance decisions are delegated to {@link ComplianceRules} (domain layer),
 * keeping this class focused on orchestration and persistence coordination.
 */
@Service
public class LedgerService {

    /** Outcome wrapper so the controller can pick the right HTTP status. */
    public record PostOutcome(TradeResultDto result, boolean created) {
    }

    private final LedgerRepository repo;
    private final ComplianceRules complianceRules;
    private final ObjectMapper objectMapper;

    public LedgerService(LedgerRepository repo, ComplianceRules complianceRules,
                         ObjectMapper objectMapper) {
        this.repo = repo;
        this.complianceRules = complianceRules;
        this.objectMapper = objectMapper;
    }

    public boolean accountExists(String accountId) {
        return repo.getCash(accountId) != null;
    }

    @Transactional
    public PostOutcome postTrade(TradeRequestDto req) {
        // 1) Idempotency: a retried request_id returns the original outcome, no double-post.
        var existing = repo.findTradeByRequestId(req.request_id());
        if (existing.isPresent()) {
            return new PostOutcome(existing.get(), false);
        }

        OffsetDateTime now = OffsetDateTime.now(ZoneOffset.UTC);
        BigDecimal cash = repo.getCash(req.account_id());
        BigDecimal amount = req.price().multiply(req.quantity());
        boolean isBuy = "BUY".equals(req.side());
        BigDecimal cashDelta = isBuy ? amount.negate() : amount;
        BigDecimal cashAfter = cash.add(cashDelta);

        // Projected net position for this symbol if the trade were applied.
        BigDecimal currentPosition = repo.positionAfter(req.account_id(), req.symbol());
        BigDecimal signedQty = isBuy ? req.quantity() : req.quantity().negate();
        BigDecimal positionAfter = currentPosition.add(signedQty);

        // 2) Compliance: reject (but still audit) on the first violated rule.
        Optional<String> violation = complianceRules.firstViolation(cashAfter, positionAfter);
        if (violation.isPresent()) {
            String reason = violation.get();
            repo.insertTrade(UUID.randomUUID(), req.request_id(), req.account_id(), req.symbol(),
                    req.side(), req.quantity(), req.price(), "rejected", reason, now);
            repo.insertAudit(UUID.randomUUID(), req.account_id(), req.request_id(), "POST_TRADE",
                    "rejected", reason, now);
            return new PostOutcome(
                    new TradeResultDto(req.request_id(), null, req.symbol(), req.side(),
                            req.quantity(), req.price(), "rejected", reason, null), true);
        }

        // 3) Accept: trade + balanced journal + cash + audit + outbox (atomic).
        UUID tradeId = UUID.randomUUID();
        UUID journalEntryId = UUID.randomUUID();

        repo.insertTrade(tradeId, req.request_id(), req.account_id(), req.symbol(), req.side(),
                req.quantity(), req.price(), "posted", null, now);
        repo.insertJournalEntry(journalEntryId, req.request_id(), req.account_id(), now);

        // Double-entry: mirrored debit/credit between the securities and cash accounts.
        if (isBuy) {
            repo.insertJournalLine(journalEntryId, "securities", amount, BigDecimal.ZERO);
            repo.insertJournalLine(journalEntryId, req.account_id(), BigDecimal.ZERO, amount);
        } else {
            repo.insertJournalLine(journalEntryId, req.account_id(), amount, BigDecimal.ZERO);
            repo.insertJournalLine(journalEntryId, "securities", BigDecimal.ZERO, amount);
        }

        repo.updateCash(req.account_id(), cashDelta);
        repo.insertAudit(UUID.randomUUID(), req.account_id(), req.request_id(), "POST_TRADE",
                "accepted", null, now);

        repo.insertOutbox(UUID.randomUUID(), "LedgerUpdated",
                buildLedgerUpdatedEnvelope(req, journalEntryId, cashDelta, positionAfter, now), now);

        return new PostOutcome(
                new TradeResultDto(req.request_id(), journalEntryId.toString(), req.symbol(),
                        req.side(), req.quantity(), req.price(), "posted", null, now), true);
    }

    /** Serializes a LedgerUpdated.v1 envelope (matches docs/contracts/events). */
    private String buildLedgerUpdatedEnvelope(TradeRequestDto req, UUID journalEntryId,
                                              BigDecimal cashDelta, BigDecimal positionAfter,
                                              OffsetDateTime postedAt) {
        String correlationId = MDC.get("correlation_id");
        if (correlationId == null || correlationId.isBlank()) {
            correlationId = UUID.randomUUID().toString();
        }

        Map<String, Object> data = new LinkedHashMap<>();
        data.put("journal_entry_id", journalEntryId.toString());
        data.put("source_event_id", req.request_id().toString());
        data.put("account_id", req.account_id());
        data.put("symbol", req.symbol());
        data.put("side", req.side());
        data.put("quantity", req.quantity());
        data.put("price", req.price());
        data.put("cash_delta", cashDelta);
        data.put("position_after", positionAfter);
        data.put("posted_at", postedAt.toString());

        Map<String, Object> envelope = new LinkedHashMap<>();
        envelope.put("event_id", UUID.randomUUID().toString());
        envelope.put("event_type", "LedgerUpdated");
        envelope.put("schema_version", "1");
        envelope.put("correlation_id", correlationId);
        envelope.put("produced_at", postedAt.toString());
        envelope.put("producer", "ledger-core");
        envelope.put("data", data);

        try {
            return objectMapper.writeValueAsString(envelope);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException("failed to serialize LedgerUpdated envelope", e);
        }
    }
}
