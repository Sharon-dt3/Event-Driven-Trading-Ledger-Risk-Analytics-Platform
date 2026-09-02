package com.tradepulse.ledger.stream;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * Phase 5 configuration for the ledger-core Redis Streams publisher.
 *
 * <p>These values describe <em>how</em> committed ledger postings will eventually
 * be relayed from the transactional outbox to the {@code ledger.updates} Redis
 * stream. Task&nbsp;1 only introduces the plumbing (client + thin XADD wrapper +
 * config); the relay loop that consumes {@link #getPollIntervalMs()} /
 * {@link #getBatchSize()} is added in a later task. The publisher stays inert
 * while {@link #isEnabled()} is {@code false} (the default).
 */
@ConfigurationProperties(prefix = "ledger.stream")
public class LedgerStreamProperties {

    /** Master switch for the outbox relay. Off by default (no behavior yet). */
    private boolean enabled = false;

    /** Target Redis stream key for {@code LedgerUpdated.v1} events. */
    private String name = "ledger.updates";

    /** How often the (future) relay polls the outbox for new events, in ms. */
    private long pollIntervalMs = 1000;

    /** Max outbox rows the (future) relay drains per poll. */
    private int batchSize = 100;

    public boolean isEnabled() {
        return enabled;
    }

    public void setEnabled(boolean enabled) {
        this.enabled = enabled;
    }

    public String getName() {
        return name;
    }

    public void setName(String name) {
        this.name = name;
    }

    public long getPollIntervalMs() {
        return pollIntervalMs;
    }

    public void setPollIntervalMs(long pollIntervalMs) {
        this.pollIntervalMs = pollIntervalMs;
    }

    public int getBatchSize() {
        return batchSize;
    }

    public void setBatchSize(int batchSize) {
        this.batchSize = batchSize;
    }
}
