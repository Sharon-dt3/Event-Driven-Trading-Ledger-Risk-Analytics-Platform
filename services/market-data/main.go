package main

import (
	"context"
	"log/slog"
	"net/http"
	"os/signal"
	"syscall"
	"time"

	"github.com/tradepulse/common-go/httpkit"
)

const serviceName = "market-data"
const version = "0.2.0"

// newRouter builds the HTTP handler for liveness/readiness and service
// metadata. Kept small and side-effect free so it can be exercised in tests.
func newRouter(logger *slog.Logger) http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/health", httpkit.HealthHandler(serviceName))
	mux.HandleFunc("/healthz", httpkit.HealthHandler(serviceName))
	mux.HandleFunc("/", httpkit.RootHandler(serviceName, version))
	return httpkit.Wrap(logger, mux)
}

func main() {
	logger := httpkit.NewLogger(serviceName)
	cfg := loadConfig()

	// Cancel on SIGINT/SIGTERM for graceful shutdown.
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	// Redis publisher: connects lazily and reconnects on each publish, so the
	// service stays up (and healthy) even if Redis is briefly unavailable.
	redis := newRedisClient(cfg.redisAddr)
	defer redis.Close()
	if err := redis.Ping(ctx); err != nil {
		logger.Warn("redis not reachable at startup; will retry on publish",
			slog.String("redis_addr", cfg.redisAddr),
			slog.String("error", err.Error()))
	} else {
		logger.Info("connected to redis", slog.String("redis_addr", cfg.redisAddr))
	}

	source := resolveSource(cfg, logger)
	producer := &Producer{
		cfg:    cfg,
		pub:    redis,
		src:    newSyntheticSource(cfg.symbols),
		source: source,
		logger: logger,
	}
	go producer.Run(ctx)

	srv := &http.Server{
		Addr:         ":" + cfg.port,
		Handler:      newRouter(logger),
		ReadTimeout:  10 * time.Second,
		WriteTimeout: 10 * time.Second,
	}

	go func() {
		logger.Info("starting service", slog.String("addr", srv.Addr))
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			logger.Error("server stopped", slog.String("error", err.Error()))
			stop()
		}
	}()

	<-ctx.Done()
	logger.Info("shutdown signal received")

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := srv.Shutdown(shutdownCtx); err != nil {
		logger.Error("graceful shutdown failed", slog.String("error", err.Error()))
	}
	logger.Info("service stopped")
}
