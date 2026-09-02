package com.tradepulse.ledger.stream;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;

/**
 * Phase 5 Task 3 dedupe unit test (no Redis).
 *
 * <p>Exercises the Redis-free {@link Phase5PocConsumer#handle(String)} path to
 * prove the core guarantee &mdash; two entries carrying the same envelope
 * {@code event_id} produce exactly one applied effect &mdash; without needing a
 * broker, so it runs in the default suite.
 */
class Phase5PocConsumerTest {

    private Phase5PocConsumer newConsumer() {
        return new Phase5PocConsumer(
                mock(StringRedisTemplate.class),
                new ObjectMapper(),
                new LedgerStreamProperties(),
                new Phase5ConsumerProperties());
    }

    private String envelope(String eventId) {
        return "{\"event_id\":\"" + eventId + "\",\"event_type\":\"LedgerUpdated\","
                + "\"schema_version\":\"1\",\"data\":{\"account_id\":\"acct_123\","
                + "\"symbol\":\"MSFT\",\"position_after\":3}}";
    }

    @Test
    void duplicateEventIds_yieldExactlyOneAppliedEffect() {
        Phase5PocConsumer consumer = newConsumer();
        String eventId = UUID.randomUUID().toString();
        String json = envelope(eventId);

        assertThat(consumer.handle(json)).isTrue();   // first: applied
        assertThat(consumer.handle(json)).isFalse();  // duplicate: skipped

        assertThat(consumer.appliedCount()).isEqualTo(1);
        assertThat(consumer.skippedCount()).isEqualTo(1);
        assertThat(consumer.positionView()).hasSize(1);
        assertThat(consumer.positionView()).containsEntry("acct_123|MSFT", "3");
    }

    @Test
    void distinctEventIds_areEachApplied() {
        Phase5PocConsumer consumer = newConsumer();

        assertThat(consumer.handle(envelope(UUID.randomUUID().toString()))).isTrue();
        assertThat(consumer.handle(envelope(UUID.randomUUID().toString()))).isTrue();

        assertThat(consumer.appliedCount()).isEqualTo(2);
        assertThat(consumer.skippedCount()).isZero();
    }

    @Test
    void missingEventId_isSkippedSafely() {
        Phase5PocConsumer consumer = newConsumer();

        assertThat(consumer.handle("{\"data\":{}}")).isFalse();
        assertThat(consumer.appliedCount()).isZero();
    }
}
