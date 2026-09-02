package main

import (
	"context"
	"log/slog"
	"net/http"
	"os"
	"time"

	"github.com/tradepulse/common-go/httpkit"
)

const serviceName = "gateway"

func newRouter(logger *slog.Logger, broker *Broker) http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/health", httpkit.HealthHandler(serviceName))
	mux.HandleFunc("/healthz", httpkit.HealthHandler(serviceName))

	// Realtime browser feed: fan-out of market.ticks + risk.updates as SSE.
	mux.HandleFunc("/stream", sseHandler(broker))

	// Legacy placeholder retained for compatibility; the realtime channel is
	// now the SSE endpoint GET /stream.
	mux.HandleFunc("/ws", func(w http.ResponseWriter, r *http.Request) {
		httpkit.WriteJSON(w, http.StatusNotImplemented, map[string]string{
			"error":   "not_implemented",
			"detail":  "use GET /stream for the SSE realtime feed",
			"service": serviceName,
		})
	})

	mux.HandleFunc("/", httpkit.RootHandler(serviceName, "0.2.0"))
	return httpkit.Wrap(logger, mux)
}

func envOr(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func main() {
	logger := httpkit.NewLogger(serviceName)

	port := envOr("PORT", "8084")
	redisAddr := envOr("REDIS_ADDR", "localhost:6379")
	ticksStream := envOr("MARKET_DATA_STREAM", "market.ticks")
	riskStream := envOr("RISK_STREAM", "risk.updates")

	broker := newBroker()

	rc := newRedisClient(redisAddr)
	defer rc.Close()

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	tailer := &streamTailer{
		rdb:    rc.rdb,
		broker: broker,
		logger: logger,
		streams: map[string]string{
			ticksStream: "ticks",
			riskStream:  "risk",
		},
	}
	go tailer.run(ctx)

	srv := &http.Server{
		Addr:        ":" + port,
		Handler:     newRouter(logger, broker),
		ReadTimeout: 10 * time.Second,
		// No WriteTimeout: SSE responses are intentionally long-lived.
	}

	logger.Info("starting service",
		slog.String("addr", srv.Addr),
		slog.String("redis_addr", redisAddr),
		slog.String("ticks_stream", ticksStream),
		slog.String("risk_stream", riskStream))
	if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		logger.Error("server stopped", slog.String("error", err.Error()))
		os.Exit(1)
	}
}
