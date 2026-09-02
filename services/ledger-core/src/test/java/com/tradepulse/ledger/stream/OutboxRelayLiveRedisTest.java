package com.tradepulse.ledger.stream;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.data.domain.Range;
import org.springframework.data.redis.connection.stream.MapRecord;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.TestPropertySource;

/**
 * Phase 5 <strong>live wire-path</strong> integration check for the outbox relay.
 *
 * <p>Unlike {@link OutboxRelayTest} (which mocks {@link StreamPublisher}), this
 * test exercises the <em>real</em> {@code OutboxRelay} + {@code StreamPublisher}
 * against a running local Redis, so it proves the thing the mock cannot: that a
 * real {@code XADD} lands an entry on the {@code ledger.updates} stream with the
 * exact platform field layout &mdash; {@code event_type}, {@code schema_version},
 * and {@code event=<full envelope JSON>} &mdash; and that the outbox row flips to
 * {@code sent=true}.
 *
 * <p>It is disabled unless {@code REDIS_IT=1} is set in the environment, so the
 * default {@code mvn verify} (with Redis down) stays green; run it explicitly
 * with a local {@code redis-server} up:
 * <pre>REDIS_IT=1 mvn -Dtest=OutboxRelayLiveRedisTest test</pre>
 * The DB layer still uses the suite's H2/Flyway schema (no Postgres required).
 */
@SpringBootTest
@EnabledIfEnvironmentVariable(named = "REDIS_IT", matches = "1")
@TestPropertySource(properties = {
        "ledger.stream.enabled=true",
        "ledger.stream.name=ledger.updates",
        // Park the @Scheduled poller so the test drives relayBatch() itself.
        "ledger.stream.poll-interval-ms=3600000",
        "ledger.stream.batch-size=100",
        "spring.data.redis.url=redis://localhost:6379/0"
})
class OutboxRelayLiveRedisTest {

    private static final String STREAM = "ledger.updates";

    @Autowired
    OutboxRelay relay;

    @Autowired
    JdbcTemplate jdbc;

    @Autowired
    StringRedisTemplate redis;

    @BeforeEach
    void reset() {
        jdbc.update("DELETE FROM outbox_events");
        redis.delete(STREAM); // start from an empty stream for a deterministic read-back
    }

    @Test
    void realRelay_publishesEnvelopeFields_toRealStream_andMarksSent() {
        UUID eventId = UUID.randomUUID();
        String envelopeEventId = UUID.randomUUID().toString();
        String payload = "{\"event_id\":\"" + envelopeEventId + "\","
                + "\"event_type\":\"LedgerUpdated\",\"schema_version\":\"1\","
                + "\"producer\":\"ledger-core\","
                + "\"data\":{\"account_id\":\"acct_123\",\"symbol\":\"MSFT\",\"position_after\":3}}";
        jdbc.update(
                "INSERT INTO outbox_events(event_id, event_type, payload, sent, created_at) "
                        + "VALUES (?,?,?,?,?)",
                eventId, "LedgerUpdated", payload, Boolean.FALSE,
                OffsetDateTime.now(ZoneOffset.UTC));

        int published = relay.relayBatch();

        assertThat(published).isEqualTo(1);

        // The row flipped to sent=true after a real publish.
        Boolean sent = jdbc.queryForObject(
                "SELECT sent FROM outbox_events WHERE event_id = ?", Boolean.class, eventId);
        assertThat(sent).isTrue();

        // A real entry landed on the real stream with the expected field layout.
        List<MapRecord<String, String, String>> records =
                redis.<String, String>opsForStream().range(STREAM, Range.unbounded());
        assertThat(records).hasSize(1);

        Map<String, String> fields = records.get(0).getValue();
        assertThat(fields.get("event_type")).isEqualTo("LedgerUpdated");
        assertThat(fields.get("schema_version")).isEqualTo("1");
        // The full envelope JSON is carried verbatim under "event".
        assertThat(fields.get("event")).isEqualTo(payload);
        assertThat(fields.get("event")).contains("\"event_id\":\"" + envelopeEventId + "\"");
    }
}
