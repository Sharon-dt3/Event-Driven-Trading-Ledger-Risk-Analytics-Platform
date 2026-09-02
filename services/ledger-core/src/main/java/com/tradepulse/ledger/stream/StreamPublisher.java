package com.tradepulse.ledger.stream;

import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.connection.stream.RecordId;
import org.springframework.data.redis.core.StringRedisTemplate;

/**
 * Phase 5 (Task 1) &mdash; a minimal wrapper over Redis Streams {@code XADD}.
 *
 * <p>This isolates the "can we talk to Redis" concern from the outbox relay
 * logic that arrives in a later task. It performs exactly one {@code XADD} to the
 * configured stream ({@link LedgerStreamProperties#getName()}) and returns the
 * generated {@link RecordId}. When the relay is disabled
 * ({@code ledger.stream.enabled=false}, the default) {@link #publish(Map)} is a
 * no-op that returns {@code null}, so the bean can be wired without driving any
 * behavior yet.
 *
 * <p>Note: {@link StringRedisTemplate} uses Lettuce, which connects lazily, so
 * merely constructing this bean does not open a Redis connection.
 */
public class StreamPublisher {

    private static final Logger log = LoggerFactory.getLogger(StreamPublisher.class);

    private final StringRedisTemplate redisTemplate;
    private final LedgerStreamProperties properties;

    public StreamPublisher(StringRedisTemplate redisTemplate, LedgerStreamProperties properties) {
        this.redisTemplate = redisTemplate;
        this.properties = properties;
    }

    /**
     * Append one entry to the configured Redis stream via {@code XADD}.
     *
     * @param fields the flat field/value map for the stream entry (e.g. an
     *     envelope's serialized fields)
     * @return the assigned {@link RecordId}, or {@code null} when publishing is
     *     disabled
     */
    public RecordId publish(Map<String, String> fields) {
        if (!properties.isEnabled()) {
            log.debug("StreamPublisher disabled; skipping XADD to '{}'", properties.getName());
            return null;
        }
        RecordId id = redisTemplate.opsForStream().add(properties.getName(), fields);
        log.debug("XADD '{}' -> {}", properties.getName(), id);
        return id;
    }

    /** The Redis stream key this publisher targets. */
    public String streamName() {
        return properties.getName();
    }

    /** Whether publishing is currently enabled. */
    public boolean isEnabled() {
        return properties.isEnabled();
    }
}
