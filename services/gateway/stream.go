package main

import (
	"context"
	"log/slog"
	"time"

	"github.com/redis/go-redis/v9"
)

// streamTailer performs a blocking XREAD across the configured Redis streams,
// starting from "$" (only entries added after connect), and forwards each
// entry's full envelope JSON (stored under the "event" field by the platform
// producers) to the broker as an SSE message named by the stream's logical
// channel (e.g. "ticks", "risk").
type streamTailer struct {
	rdb     *redis.Client
	broker  *Broker
	logger  *slog.Logger
	streams map[string]string // redis stream name -> SSE event name
}

func (t *streamTailer) run(ctx context.Context) {
	streamNames := make([]string, 0, len(t.streams))
	for s := range t.streams {
		streamNames = append(streamNames, s)
	}

	// Track the last-seen id per stream; "$" means "only new entries".
	lastID := make(map[string]string, len(streamNames))
	for _, s := range streamNames {
		lastID[s] = "$"
	}

	t.logger.Info("stream tailer started", slog.Any("streams", streamNames))

	for {
		if ctx.Err() != nil {
			return
		}

		// XReadArgs.Streams is [stream1, stream2, ..., id1, id2, ...].
		args := make([]string, 0, len(streamNames)*2)
		args = append(args, streamNames...)
		for _, s := range streamNames {
			args = append(args, lastID[s])
		}

		res, err := t.rdb.XRead(ctx, &redis.XReadArgs{
			Streams: args,
			Block:   5 * time.Second,
			Count:   128,
		}).Result()
		if err != nil {
			if err == redis.Nil {
				continue // block window elapsed with no new entries
			}
			if ctx.Err() != nil {
				return
			}
			t.logger.Warn("xread failed; retrying", slog.String("error", err.Error()))
			time.Sleep(time.Second)
			continue
		}

		for _, stream := range res {
			eventName := t.streams[stream.Stream]
			for _, m := range stream.Messages {
				lastID[stream.Stream] = m.ID
				payload, _ := m.Values["event"].(string)
				if payload == "" {
					continue
				}
				t.broker.publish(Message{Event: eventName, Data: payload})
			}
		}
	}
}
