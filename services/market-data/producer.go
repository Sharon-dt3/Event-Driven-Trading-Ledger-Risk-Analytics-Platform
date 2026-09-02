package main

import (
	"context"
	"encoding/json"
	"log/slog"
	"time"
)

// publisher is the minimal interface the producer needs to emit ticks. It is
// satisfied by *RedisClient and by fakes in tests.
type publisher interface {
	XAdd(ctx context.Context, stream string, maxLen int64, fields map[string]string) (string, error)
}

// Producer periodically generates ticks and publishes them to the configured
// stream as TickReceived.v1 envelopes.
type Producer struct {
	cfg    config
	pub    publisher
	src    *SyntheticSource
	source string // effective data-source label recorded on each tick
	logger *slog.Logger
}

// resolveSource decides the effective tick source. Live Finnhub ingestion is not
// enabled in this build, so a "finnhub" request logs a warning and falls back to
// synthetic generation.
func resolveSource(cfg config, logger *slog.Logger) string {
	switch cfg.source {
	case sourceFinnhub:
		logger.Warn("finnhub source requested but live ingestion is not enabled in this build; falling back to synthetic",
			slog.Bool("finnhub_api_key_present", cfg.finnhubAPIKey != ""))
		return sourceSynthetic
	case sourceSynthetic, "":
		return sourceSynthetic
	default:
		logger.Warn("unknown MARKET_DATA_SOURCE; falling back to synthetic",
			slog.String("requested", cfg.source))
		return sourceSynthetic
	}
}

// Run publishes one round of ticks per interval until ctx is cancelled.
func (p *Producer) Run(ctx context.Context) {
	ticker := time.NewTicker(p.cfg.tickInterval)
	defer ticker.Stop()

	p.logger.Info("market-data producer started",
		slog.String("stream", p.cfg.stream),
		slog.String("source", p.source),
		slog.Any("symbols", p.cfg.symbols),
		slog.Duration("interval", p.cfg.tickInterval))

	for {
		select {
		case <-ctx.Done():
			p.logger.Info("market-data producer stopping")
			return
		case <-ticker.C:
			p.publishOnce(ctx)
		}
	}
}

// publishOnce emits exactly one tick per configured symbol.
func (p *Producer) publishOnce(ctx context.Context) {
	for _, sym := range p.cfg.symbols {
		price, volume := p.src.Next(sym)
		env := newTickEnvelope(sym, price, volume, p.source, newUUID())

		payload, err := json.Marshal(env)
		if err != nil {
			p.logger.Error("marshal tick", slog.String("symbol", sym), slog.String("error", err.Error()))
			continue
		}

		// Store the full envelope under "event"; expose type/version as separate
		// fields for easy inspection and consumer-side filtering.
		fields := map[string]string{
			"event_type":     env.EventType,
			"schema_version": env.SchemaVersion,
			"event":          string(payload),
		}

		id, err := p.pub.XAdd(ctx, p.cfg.stream, p.cfg.streamMaxLen, fields)
		if err != nil {
			p.logger.Warn("publish tick failed",
				slog.String("symbol", sym),
				slog.String("stream", p.cfg.stream),
				slog.String("error", err.Error()))
			continue
		}

		p.logger.Debug("published tick",
			slog.String("symbol", sym),
			slog.Float64("price", price),
			slog.String("stream", p.cfg.stream),
			slog.String("entry_id", id),
			slog.String("correlation_id", env.CorrelationID))
	}
}
