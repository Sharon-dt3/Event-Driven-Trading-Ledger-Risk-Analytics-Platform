package com.tradepulse.ledger.stream;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.connection.stream.Consumer;
import org.springframework.data.redis.connection.stream.MapRecord;
import org.springframework.data.redis.connection.stream.RecordId;
import org.springframework.data.redis.connection.stream.StreamOffset;
import org.springframework.data.redis.connection.stream.StreamReadOptions;
import org.springframework.data.redis.core.StreamOperations;
import org.springframework.data.redis.core.StringRedisTemplate;

/**
 * Phase 5 Task 6 &mdash; CI guard for duplicate-delivery idempotency through the
 * consumer's real {@link Phase5PocConsumer#pollOnce()} stream path, WITHOUT a
 * broker.
 *
 * <p>Coverage split across the Phase 5 consumer tests:
 * <ul>
 *   <li>{@link Phase5PocConsumerTest} proves the pure {@code handle()} dedupe;</li>
 *   <li>{@link Phase5PocConsumerLiveRedisTest} proves the full wire path, but
 *       only when {@code REDIS_IT=1} (skipped in the normal build);</li>
 *   <li><b>this test</b> closes the gap in between &mdash; it mocks
 *       {@link StreamOperations} so {@code pollOnce()} reads two stream entries
 *       carrying the <em>same</em> envelope {@code event_id}, and asserts exactly
 *       one applied effect while both entries are still {@code XACK}ed.</li>
 * </ul>
 *
 * <p>Because it uses only Mockito (no Testcontainers, no live Redis), it runs in
 * the default {@code mvn verify} flow, so CI guards the idempotency behavior that
 * the manual {@code poc/native-kill-restart} script proves end-to-end.
 */
class Phase5PocConsumerPollDedupeTest {

    @SuppressWarnings("unchecked")
    @Test
    void pollOnce_duplicateDelivery_appliesOnce_andAcksBoth() {
        StringRedisTemplate redis = mock(StringRedisTemplate.class);
        StreamOperations<String, Object, Object> streamOps = mock(StreamOperations.class);
        when(redis.opsForStream()).thenReturn(streamOps);

        String eventId = UUID.randomUUID().toString();
        String payload = "{\"event_id\":\"" + eventId + "\",\"event_type\":\"LedgerUpdated\","
                + "\"schema_version\":\"1\",\"data\":{\"account_id\":\"acct_123\","
                + "\"symbol\":\"MSFT\",\"position_after\":3}}";

        // Two DISTINCT stream entries (different record ids) carrying the SAME
        // envelope event_id -> an at-least-once duplicate on the wire.
        MapRecord<String, String, String> rec1 = mock(MapRecord.class);
        when(rec1.getValue()).thenReturn(Map.of("event", payload));
        when(rec1.getId()).thenReturn(RecordId.of("1-0"));
        MapRecord<String, String, String> rec2 = mock(MapRecord.class);
        when(rec2.getValue()).thenReturn(Map.of("event", payload));
        when(rec2.getId()).thenReturn(RecordId.of("2-0"));

        when(streamOps.read(any(Consumer.class), any(StreamReadOptions.class),
                any(StreamOffset.class))).thenReturn(List.of(rec1, rec2));
        when(streamOps.acknowledge(anyString(), anyString(), any(RecordId.class)))
                .thenReturn(1L);

        Phase5PocConsumer consumer = new Phase5PocConsumer(
                redis, new ObjectMapper(),
                new LedgerStreamProperties(), new Phase5ConsumerProperties());

        int consumed = consumer.pollOnce();

        assertThat(consumed).isEqualTo(2);                // both entries read + acked
        assertThat(consumer.appliedCount()).isEqualTo(1); // dedupe: one applied effect
        assertThat(consumer.skippedCount()).isEqualTo(1); // duplicate event_id skipped
        assertThat(consumer.positionView()).containsEntry("acct_123|MSFT", "3");
        // Both entries are acked, so neither lingers pending (no redelivery loop).
        verify(streamOps, times(2)).acknowledge(anyString(), anyString(), any(RecordId.class));
    }
}
