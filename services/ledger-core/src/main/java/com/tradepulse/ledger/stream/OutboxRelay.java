package com.tradepulse.ledger.stream;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.tradepulse.ledger.ledger.LedgerRepository;
import com.tradepulse.ledger.ledger.OutboxEvent;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * Phase 5 (Task 2) &mdash; the transactional-outbox relay.
 *
 * <p>A scheduled worker drains {@code outbox_events WHERE sent=false} oldest-first
 * and, for each row, performs <strong>publish-then-mark-sent</strong>: it
 * {@code XADD}s the event to the {@code ledger.updates} stream via
 * {@link StreamPublisher} and only then flips {@code sent=true}. If publishing a
 * row fails, the batch stops <em>without</em> marking that row, so it (and every
 * later row) stays unsent and is re-published on the next cycle. This yields
 * <em>at-least-once</em> delivery: a crash between publish and mark simply causes
 * a duplicate publish later, which downstream consumers dedupe by envelope
 * {@code event_id}.
 */
@Component
public class OutboxRelay {

    private static final Logger log = LoggerFactory.getLogger(OutboxRelay.class);

    private final LedgerRepository repo;
    private final StreamPublisher publisher;
    private final LedgerStreamProperties properties;
    private final ObjectMapper objectMapper;

    public OutboxRelay(LedgerRepository repo, StreamPublisher publisher,
                       LedgerStreamProperties properties, ObjectMapper objectMapper) {
        this.repo = repo;
        this.publisher = publisher;
        this.properties = properties;
        this.objectMapper = objectMapper;
    }

    /**
     * Poll the outbox on a fixed delay. Inert while the relay is disabled
     * (default), so no Redis traffic occurs until {@code ledger.stream.enabled=true}.
     */
    @Scheduled(fixedDelayString = "${ledger.stream.poll-interval-ms:1000}",
            initialDelayString = "${ledger.stream.poll-interval-ms:1000}")
    public void drainScheduled() {
        if (!properties.isEnabled()) {
            return;
        }
        try {
            int published = relayBatch();
            if (published > 0) {
                log.debug("outbox relay published {} event(s) to '{}'",
                        published, publisher.streamName());
            }
        } catch (RuntimeException ex) {
            log.warn("outbox relay cycle failed; will retry next poll", ex);
        }
    }

    /**
     * Drain one batch of unsent outbox rows using publish-then-mark-sent.
     *
     * @return the number of rows successfully published and marked sent
     */
    public int relayBatch() {
        if (!properties.isEnabled()) {
            // Never mark rows sent while disabled (publishing is a no-op) — that
            // would silently drop events.
            return 0;
        }
        List<OutboxEvent> unsent = repo.findUnsent(properties.getBatchSize());
        int published = 0;
        for (OutboxEvent event : unsent) {
            try {
                publisher.publish(toFields(event));
            } catch (RuntimeException ex) {
                // Leave this row (and all later rows) unsent; retry next cycle.
                log.warn("publish failed for outbox event {}; leaving unsent for retry",
                        event.eventId(), ex);
                break;
            }
            repo.markSent(event.eventId());
            published++;
        }
        return published;
    }

    /**
     * Build the Redis stream entry fields for an outbox row, matching the
     * platform convention (see market-data producer): the full envelope JSON is
     * carried under {@code event}, with {@code event_type} / {@code schema_version}
     * exposed as separate fields for easy inspection and consumer filtering.
     */
    private Map<String, String> toFields(OutboxEvent event) {
        String schemaVersion = "1";
        try {
            JsonNode node = objectMapper.readTree(event.payload());
            if (node.hasNonNull("schema_version")) {
                schemaVersion = node.get("schema_version").asText();
            }
        } catch (Exception ignored) {
            // Fall back to the default schema version if payload isn't parseable.
        }
        Map<String, String> fields = new LinkedHashMap<>();
        fields.put("event_type", event.eventType());
        fields.put("schema_version", schemaVersion);
        fields.put("event", event.payload());
        return fields;
    }
}
