package main

import (
	"context"
	"time"

	"github.com/redis/go-redis/v9"
)

// RedisClient is a thin wrapper over go-redis used by the gateway to tail
// market.ticks and risk.updates. The underlying *redis.Client manages its own
// connection pool and reconnection, so the tailer can simply retry on error.
type RedisClient struct {
	rdb *redis.Client
}

func newRedisClient(addr string) *RedisClient {
	return &RedisClient{
		rdb: redis.NewClient(&redis.Options{
			Addr:        addr,
			DialTimeout: 5 * time.Second,
			ReadTimeout: 0, // blocking XREAD holds the read open; disable client read timeout
		}),
	}
}

// Ping performs a connectivity check.
func (c *RedisClient) Ping(ctx context.Context) error {
	return c.rdb.Ping(ctx).Err()
}

// Close releases the underlying connection pool.
func (c *RedisClient) Close() error {
	return c.rdb.Close()
}
