package com.tradepulse.ledger.stream;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.data.redis.connection.stream.Consumer;
import org.springframework.data.redis.connection.stream.MapRecord;
import org.springframework.data.redis.connection.stream.ReadOffset;
import org.springframework.data.redis.connection.stream.StreamOffset;
import org.springframework.data.redis.connection.stream.StreamReadOptions;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.test.context.TestPropertySource;

/**
 * Phase 5 Task 3 <strong>live wire-path</strong> proof for the POC consumer.
 *
 * <p>Runs the real {@link Phase5PocConsumer} against a running local Redis to
 * prove both "done when" criteria:
 * <ol>
 *   <li>feeding two stream entries with the same envelope {@code event_id}
 *       yields exactly one applied effect (strict dedupe over a real stream);</li>
 *   <li>a pending entry left un-acked by a crashed consumer is reclaimed via
 *       {@code XAUTOCLAIM} and reprocessed <em>without double-applying</em>.</li>
 * </ol>
 *
 * <p>Disabled unless {@code REDIS_IT=1}; run with a local {@code redis-server}:
 * <pre>REDIS_IT=1 mvn -Dtest=Phase5PocConsumerLiveRedisTest test</pre>
 */
@SpringBootTest
@EnabledIfEnvironmentVariable(named = "REDIS_IT", matches = "1")
@TestPropertySource(properties = {
        "ledger.stream.name=ledger.updates",
        "ledger.consumer.enabled=false", // drive methods directly for determinism
        "ledger.consumer.group=cg:phase5-poc",
        "ledger.consumer.name=phase5-poc-1",
        "ledger.consumer.min-idle-ms=0", // reclaim eligible immediately
        "ledger.consumer.batch-size=100",
        "spring.data.redis.url=redis://localhost:6379/0"
})
class Phase5PocConsumerLiveRedisTest {

    private static final String STREAM = "ledger.updates";
    private static final String GROUP = "cg:phase5-poc";
    private static final String NAME = "phase5-poc-1";

    @Autowired
    Phase5PocConsumer consumer;

    @Autowired
    StringRedisTemplate redis;

    @BeforeEach
    void reset() {
        redis.delete(STREAM);     // dropping the stream also drops its groups
        consumer.resetForTest();
        consumer.ensureGroup();   // recreate group (MKSTREAM) at latest offset
    }

    private Map<String, String> entryFields(String envelopeEventId) {
        String payload = "{\"event_id\":\"" + envelopeEventId + "\","
                + "\"event_type\":\"LedgerUpdated\",\"schema_version\":\"1\","
                + "\"data\":{\"account_id\":\"acct_123\",\"symbol\":\"MSFT\",\"position_after\":3}}";
        Map<String, String> fields = new LinkedHashMap<>();
        fields.put("event_type", "LedgerUpdated");
        fields.put("schema_version", "1");
        fields.put("event", payload);
        return fields;
    }

    private long pendingCount() {
        Long total = redis.opsForStream().pending(STREAM, GROUP).getTotalPendingMessages();
        return total == null ? 0 : total;
    }

    @Test
    void duplicateEventIds_overRealStream_yieldOneAppliedEffect() {
        String eventId = UUID.randomUUID().toString();
        Map<String, String> fields = entryFields(eventId);

        // Two distinct stream entries carrying the SAME envelope event_id.
        redis.opsForStream().add(STREAM, fields);
        redis.opsForStream().add(STREAM, fields);

        int consumed = consumer.pollOnce();

        assertThat(consumed).isEqualTo(2);              // both read + acked
        assertThat(consumer.appliedCount()).isEqualTo(1); // dedupe: one effect
        assertThat(consumer.skippedCount()).isEqualTo(1);
        assertThat(consumer.positionView()).hasSize(1);
        assertThat(pendingCount()).isZero();            // nothing left pending
    }

    @Test
    void xautoclaimReclaim_reprocessesPending_withoutDoubleApplying() {
        String eventId = UUID.randomUUID().toString();
        redis.opsForStream().add(STREAM, entryFields(eventId));

        // Simulate a consumer that read + applied the entry but CRASHED before ack:
        // deliver it (now pending in the PEL) and apply once, without acking.
        List<MapRecord<String, String, String>> recs = redis.<String, String>opsForStream().read(
                Consumer.from(GROUP, NAME),
                StreamReadOptions.empty().count(10),
                StreamOffset.create(STREAM, ReadOffset.lastConsumed()));
        assertThat(recs).hasSize(1);
        consumer.handle(recs.get(0).getValue().get("event")); // applied=1, NOT acked

        assertThat(consumer.appliedCount()).isEqualTo(1);
        assertThat(pendingCount()).isEqualTo(1);        // entry stuck pending

        // Another worker reclaims the stale pending entry via XAUTOCLAIM.
        int reclaimed = consumer.reclaimStale();

        assertThat(reclaimed).isEqualTo(1);
        assertThat(consumer.appliedCount()).isEqualTo(1); // dedupe: NO double-apply
        assertThat(consumer.skippedCount()).isEqualTo(1);
        assertThat(pendingCount()).isZero();            // reclaimed entry acked
    }
}
