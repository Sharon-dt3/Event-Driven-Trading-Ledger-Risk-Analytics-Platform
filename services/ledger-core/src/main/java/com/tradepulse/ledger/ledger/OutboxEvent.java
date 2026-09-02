package com.tradepulse.ledger.ledger;

import java.util.UUID;

/**
 * A single row from {@code outbox_events} as needed by the Phase 5 relay:
 * the primary key ({@code eventId}), the {@code eventType}, and the serialized
 * event envelope ({@code payload}) that will be published to Redis.
 */
public record OutboxEvent(UUID eventId, String eventType, String payload) {
}
