package main

import (
	"log/slog"
	"net/http"
	"os"
	"time"

	"github.com/tradepulse/common-go/httpkit"
)

const serviceName = "gateway"

func newRouter(logger *slog.Logger) http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/health", httpkit.HealthHandler(serviceName))
	mux.HandleFunc("/healthz", httpkit.HealthHandler(serviceName))

	// Placeholder for the browser-facing realtime endpoint added in later phases.
	mux.HandleFunc("/ws", func(w http.ResponseWriter, r *http.Request) {
		httpkit.WriteJSON(w, http.StatusNotImplemented, map[string]string{
			"error":   "not_implemented",
			"detail":  "WS/SSE fan-out is delivered in a later phase",
			"service": serviceName,
		})
	})

	mux.HandleFunc("/", httpkit.RootHandler(serviceName, "0.1.0"))
	return httpkit.Wrap(logger, mux)
}

func main() {
	logger := httpkit.NewLogger(serviceName)

	port := os.Getenv("PORT")
	if port == "" {
		port = "8084"
	}

	srv := &http.Server{
		Addr:         ":" + port,
		Handler:      newRouter(logger),
		ReadTimeout:  10 * time.Second,
		WriteTimeout: 10 * time.Second,
	}

	logger.Info("starting service", slog.String("addr", srv.Addr))
	if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		logger.Error("server stopped", slog.String("error", err.Error()))
		os.Exit(1)
	}
}
