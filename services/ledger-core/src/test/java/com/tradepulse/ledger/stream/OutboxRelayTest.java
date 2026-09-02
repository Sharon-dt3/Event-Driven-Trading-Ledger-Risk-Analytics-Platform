package com.tradepulse.ledger.stream;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyMap;
import static org.mockito.Mockito.doReturn;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;

import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.TestPropertySource;

/**
 * Phase 5 Task 2 acceptance for the outbox relay.
 *
 * <p>Runs against the same H2/Flyway schema used by the rest of the suite. The
 * {@link StreamPublisher} is mocked so no real Redis is required; the relay is
 * enabled, and the scheduler is parked far in the future so the test drives
 * {@code relayBatch()} deterministically.
 */
@SpringBootTest
@TestPropertySource(properties = {
        "ledger.stream.enabled=true",
        // Keep the @Scheduled poller idle during the test (initial + fixed delay).
        "ledger.stream.poll-interval-ms=3600000",
        "ledger.stream.batch-size=100"
})
class OutboxRelayTest {

    @Autowired
    OutboxRelay relay;

    @Autowired
    JdbcTemplate jdbc;

    @MockBean
    StreamPublisher publisher;

    @BeforeEach
    void cleanOutbox() {
        // Isolate from outbox rows written by other tests sharing the in-memory DB.
        jdbc.update("DELETE FROM outbox_events");
    }

    private UUID insertUnsentOutbox() {
        UUID eventId = UUID.randomUUID();
        String payload = "{\"event_id\":\"" + UUID.randomUUID() + "\","
                + "\"event_type\":\"LedgerUpdated\",\"schema_version\":\"1\","
                + "\"data\":{\"account_id\":\"acct_123\",\"symbol\":\"MSFT\",\"position_after\":3}}";
        jdbc.update(
                "INSERT INTO outbox_events(event_id, event_type, payload, sent, created_at) "
                        + "VALUES (?,?,?,?,?)",
                eventId, "LedgerUpdated", payload, Boolean.FALSE,
                OffsetDateTime.now(ZoneOffset.UTC));
        return eventId;
    }

    private boolean isSent(UUID eventId) {
        Boolean sent = jdbc.queryForObject(
                "SELECT sent FROM outbox_events WHERE event_id = ?", Boolean.class, eventId);
        return Boolean.TRUE.equals(sent);
    }

    @Test
    void unsentRow_isPublishedToStream_andMarkedSent() {
        UUID eventId = insertUnsentOutbox();

        int published = relay.relayBatch();

        assertThat(published).isEqualTo(1);
        // Landed on ledger.updates (via the XADD wrapper) exactly once...
        verify(publisher, times(1)).publish(anyMap());
        // ...and the row was flipped to sent=true.
        assertThat(isSent(eventId)).isTrue();
    }

    @Test
    void crashBetweenPublishAndMark_leavesRowRepublishable() {
        UUID eventId = insertUnsentOutbox();

        // Simulate a crash during XADD: publish throws before the row is marked.
        doThrow(new RuntimeException("redis down")).when(publisher).publish(anyMap());
        int firstRun = relay.relayBatch();

        assertThat(firstRun).isZero();
        assertThat(isSent(eventId)).isFalse(); // NOT marked -> still re-publishable

        // Redis recovers: the SAME row is re-published and now marked sent.
        doReturn(null).when(publisher).publish(anyMap());
        int secondRun = relay.relayBatch();

        assertThat(secondRun).isEqualTo(1);
        assertThat(isSent(eventId)).isTrue();
        // At-least-once: the row was published twice across the two cycles.
        verify(publisher, times(2)).publish(anyMap());
    }
}
