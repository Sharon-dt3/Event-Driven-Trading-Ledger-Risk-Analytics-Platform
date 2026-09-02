package main

import (
	"context"
	"time"

	"github.com/redis/go-redis/v9"
)

// RedisClient publishes events to Redis Streams using the battle-tested
// go-redis client. It exposes only the small surface market-data needs (XADD +
// PING) so the rest of the service depends on a stable, minimal API. The
// go-redis client manages its own connection pool and reconnection.
type RedisClient struct {
	rdb *redis.Client
}

func newRedisClient(addr string) *RedisClient {
	return &RedisClient{
		rdb: redis.NewClient(&redis.Options{
			Addr:         addr,
			DialTimeout:  5 * time.Second,
			ReadTimeout:  5 * time.Second,
			WriteTimeout: 5 * time.Second,
		}),
	}
}

// XAdd appends an entry to a stream with an approximate length cap
// (`XADD <stream> MAXLEN ~ <n> * k v ...`) and returns the generated entry id.
func (c *RedisClient) XAdd(ctx context.Context, stream string, maxLen int64, fields map[string]string) (string, error) {
	args := &redis.XAddArgs{
		Stream: stream,
		Values: fields,
	}
	if maxLen > 0 {
		args.MaxLen = maxLen
		args.Approx = true
	}
	return c.rdb.XAdd(ctx, args).Result()
}

// Ping performs a connectivity check.
func (c *RedisClient) Ping(ctx context.Context) error {
	return c.rdb.Ping(ctx).Err()
}

// Close releases the underlying connection pool.
func (c *RedisClient) Close() error {
	return c.rdb.Close()
}
