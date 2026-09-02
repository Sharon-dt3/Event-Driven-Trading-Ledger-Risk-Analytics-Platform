package com.tradepulse.ledger.stream;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.domain.Range;
import org.springframework.data.redis.connection.stream.Consumer;
import org.springframework.data.redis.connection.stream.MapRecord;
import org.springframework.data.redis.connection.stream.PendingMessage;
import org.springframework.data.redis.connection.stream.PendingMessages;
import org.springframework.data.redis.connection.stream.ReadOffset;
import org.springframework.data.redis.connection.stream.RecordId;
import org.springframework.data.redis.connection.stream.StreamOffset;
import org.springframework.data.redis.connection.stream.StreamReadOptions;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * Phase 5 (Task 3) &mdash; a minimal, idempotent POC consumer of the
 * {@code ledger.updates} stream.
 *
 * <p>Reads via {@code XREADGROUP} on the throwaway group {@code cg:phase5-poc},
 * dedupes <strong>strictly by envelope {@code event_id}</strong>, applies a
 * trivial projection (a processed-events set + an in-memory positions view),
 * then {@code XACK}s. On each cycle it first reclaims stale pending entries left
 * un-acked by a crashed consumer (idle-based reclaim, equivalent to
 * {@code XAUTOCLAIM}, via Spring Data's {@code pending()}+{@code claim()}) and
 * reprocesses them &mdash; the dedupe guarantees a reclaimed entry that was
 * already applied is <em>not</em> applied twice.
 *
 * <p>Inert while {@code ledger.consumer.enabled=false} (default). The Redis
 * stream operations live here; the pure {@link #handle(String)} step is
 * Redis-free so the dedupe guarantee is unit-testable without a broker.
 */
@Component
public class Phase5PocConsumer {

    private static final Logger log = LoggerFactory.getLogger(Phase5PocConsumer.class);

    private final StringRedisTemplate redis;
    private final ObjectMapper objectMapper;
    private final LedgerStreamProperties streamProps;
    private final Phase5ConsumerProperties props;

    // Trivial projection state. NOTE (Phase 5 POC scope): dedupe is IN-MEMORY, so
    // it survives an in-flight reclaim (a running consumer reclaiming its own stale
    // pending entry) but NOT a full process restart — a fresh process starts with
    // an empty set and would re-apply. Restart-safe dedupe (a persisted
    // processed-events table or an upsert-keyed projection) belongs to the real
    // risk-engine consumer, not this throwaway cg:phase5-poc worker.
    private final java.util.Set<String> processed = ConcurrentHashMap.newKeySet();
    private final Map<String, String> positionView = new ConcurrentHashMap<>();
    private final AtomicInteger applied = new AtomicInteger();
    private final AtomicInteger skipped = new AtomicInteger();

    public Phase5PocConsumer(StringRedisTemplate redis, ObjectMapper objectMapper,
                             LedgerStreamProperties streamProps, Phase5ConsumerProperties props) {
        this.redis = redis;
        this.objectMapper = objectMapper;
        this.streamProps = streamProps;
        this.props = props;
    }

    private String stream() {
        return streamProps.getName();
    }

    /** Scheduled worker cycle: reclaim stale pending, then read new. Inert when disabled. */
    @Scheduled(fixedDelayString = "${ledger.stream.poll-interval-ms:1000}",
            initialDelayString = "${ledger.stream.poll-interval-ms:1000}")
    public void workOnce() {
        if (!props.isEnabled()) {
            return;
        }
        try {
            ensureGroup();
            reclaimStale();
            pollOnce();
        } catch (RuntimeException ex) {
            log.warn("phase5 consumer cycle failed; will retry next poll", ex);
        }
    }

    /** Create the consumer group (with MKSTREAM), tolerating an existing group. */
    public void ensureGroup() {
        try {
            redis.opsForStream().createGroup(stream(), ReadOffset.latest(), props.getGroup());
        } catch (Exception ex) {
            // BUSYGROUP (group already exists) is expected and fine.
            String msg = ex.getMessage();
            if (msg == null || !msg.contains("BUSYGROUP")) {
                log.debug("createGroup on '{}' for '{}': {}", stream(), props.getGroup(), msg);
            }
        }
    }

    /**
     * Read one batch of new entries ({@code XREADGROUP ... >}), handle each, and
     * {@code XACK} it (duplicates are acked too, so they don't linger pending).
     *
     * @return the number of entries consumed (applied or deduped) and acked
     */
    public int pollOnce() {
        List<MapRecord<String, String, String>> records = redis.<String, String>opsForStream().read(
                Consumer.from(props.getGroup(), props.getName()),
                StreamReadOptions.empty().count(props.getBatchSize()),
                StreamOffset.create(stream(), ReadOffset.lastConsumed()));
        if (records == null || records.isEmpty()) {
            return 0;
        }
        int consumed = 0;
        for (MapRecord<String, String, String> rec : records) {
            String eventJson = rec.getValue().get("event");
            if (eventJson != null) {
                handle(eventJson);
            }
            redis.opsForStream().acknowledge(stream(), props.getGroup(), rec.getId());
            consumed++;
        }
        return consumed;
    }

    /**
     * Reclaim stale pending entries (idle longer than {@code min-idle-ms}) and
     * reprocess them. This is the {@code XAUTOCLAIM} guarantee expressed with
     * Spring Data's typed {@code pending()}+{@code claim()}: list this group's
     * pending entries, claim those idle beyond the threshold to this consumer,
     * reprocess (dedupe makes an already-applied entry a no-op), then {@code XACK}.
     *
     * @return the number of pending entries reclaimed and acked
     */
    public int reclaimStale() {
        Duration minIdle = Duration.ofMillis(props.getMinIdleMs());
        PendingMessages pending = redis.opsForStream().pending(
                stream(), props.getGroup(), Range.unbounded(), props.getBatchSize());
        if (pending == null || pending.isEmpty()) {
            return 0;
        }
        int reclaimed = 0;
        for (PendingMessage pm : pending) {
            if (pm.getElapsedTimeSinceLastDelivery().compareTo(minIdle) < 0) {
                continue; // not idle long enough yet
            }
            RecordId id = pm.getId();
            List<MapRecord<String, String, String>> claimed = redis.<String, String>opsForStream()
                    .claim(stream(), props.getGroup(), props.getName(), minIdle, id);
            if (claimed == null || claimed.isEmpty()) {
                // Another consumer beat us to it, or it was acked meanwhile.
                continue;
            }
            for (MapRecord<String, String, String> rec : claimed) {
                String eventJson = rec.getValue().get("event");
                if (eventJson != null) {
                    handle(eventJson);
                }
                redis.opsForStream().acknowledge(stream(), props.getGroup(), rec.getId());
                reclaimed++;
            }
        }
        return reclaimed;
    }

    /**
     * Apply a single event with strict {@code event_id} dedupe and a trivial
     * projection. Redis-free so the dedupe guarantee is unit-testable.
     *
     * @return {@code true} if newly applied; {@code false} if a duplicate/invalid
     */
    public boolean handle(String eventJson) {
        String eventId;
        JsonNode data;
        try {
            JsonNode root = objectMapper.readTree(eventJson);
            eventId = root.path("event_id").asText(null);
            data = root.path("data");
        } catch (Exception ex) {
            log.warn("skipping unparseable event from '{}'", stream(), ex);
            return false;
        }
        if (eventId == null || eventId.isBlank()) {
            log.warn("skipping event with missing event_id from '{}'", stream());
            return false;
        }
        // Strict dedupe: Set.add is atomic and returns false for a known event_id.
        if (!processed.add(eventId)) {
            skipped.incrementAndGet();
            return false;
        }
        if (data != null && data.hasNonNull("account_id") && data.hasNonNull("symbol")) {
            String key = data.get("account_id").asText() + "|" + data.get("symbol").asText();
            positionView.put(key, data.path("position_after").asText(""));
        }
        applied.incrementAndGet();
        return true;
    }

    // --- read-only accessors for observability / tests ---

    public int appliedCount() {
        return applied.get();
    }

    public int skippedCount() {
        return skipped.get();
    }

    public Map<String, String> positionView() {
        return Map.copyOf(positionView);
    }

    /** Clears in-memory projection/dedupe state. Intended for test isolation. */
    void resetForTest() {
        processed.clear();
        positionView.clear();
        applied.set(0);
        skipped.set(0);
    }
}
