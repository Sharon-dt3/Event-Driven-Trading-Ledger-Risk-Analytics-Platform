package com.tradepulse.ledger.stream;

import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.scheduling.annotation.EnableScheduling;

/**
 * Phase 5 (Task 1) wiring for the Redis Streams publisher.
 *
 * <p>Binds {@link LedgerStreamProperties} and exposes a single
 * {@link StreamPublisher} bean built on the auto-configured
 * {@link StringRedisTemplate} (Lettuce). This is deliberately "plumbing only":
 * the bean exists and can XADD when enabled, but nothing invokes it yet.
 */
@Configuration
@EnableConfigurationProperties(LedgerStreamProperties.class)
@EnableScheduling
public class StreamPublisherConfig {

    @Bean
    public StreamPublisher streamPublisher(
            StringRedisTemplate redisTemplate, LedgerStreamProperties properties) {
        return new StreamPublisher(redisTemplate, properties);
    }
}
