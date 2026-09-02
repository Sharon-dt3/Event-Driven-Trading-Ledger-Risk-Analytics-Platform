package com.tradepulse.ledger.stream;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * Phase 5 (Task 3) configuration for the minimal idempotent POC consumer.
 *
 * <p>The consumer reads {@code ledger.updates} via {@code XREADGROUP} on a
 * throwaway consumer group ({@link #getGroup()} = {@code cg:phase5-poc}), dedupes
 * strictly by envelope {@code event_id}, applies a trivial projection, then
 * {@code XACK}s. It stays inert while {@link #isEnabled()} is {@code false}
 * (the default), so it drives no Redis traffic until explicitly turned on.
 */
@ConfigurationProperties(prefix = "ledger.consumer")
public class Phase5ConsumerProperties {

    /** Master switch for the POC consumer worker. Off by default. */
    private boolean enabled = false;

    /** Throwaway consumer group name. */
    private String group = "cg:phase5-poc";

    /** This consumer's name within the group. */
    private String name = "phase5-poc-1";

    /** Max entries read (and reclaimed) per cycle. */
    private int batchSize = 100;

    /** Min idle time (ms) before a pending entry is eligible for XAUTOCLAIM. */
    private long minIdleMs = 30000;

    public boolean isEnabled() {
        return enabled;
    }

    public void setEnabled(boolean enabled) {
        this.enabled = enabled;
    }

    public String getGroup() {
        return group;
    }

    public void setGroup(String group) {
        this.group = group;
    }

    public String getName() {
        return name;
    }

    public void setName(String name) {
        this.name = name;
    }

    public int getBatchSize() {
        return batchSize;
    }

    public void setBatchSize(int batchSize) {
        this.batchSize = batchSize;
    }

    public long getMinIdleMs() {
        return minIdleMs;
    }

    public void setMinIdleMs(long minIdleMs) {
        this.minIdleMs = minIdleMs;
    }
}
