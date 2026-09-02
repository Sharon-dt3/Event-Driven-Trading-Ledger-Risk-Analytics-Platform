// Package httpkit provides the shared HTTP server building blocks for the
// TradePulse Go services (market-data, gateway): correlation-id propagation,
// structured request logging, JSON responses, and standard health/root
// handlers. It exists to remove the copy-pasted boilerplate that previously
// lived in each service's main.go.
package httpkit

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"log/slog"
	"net/http"
	"os"
	"strings"
	"time"
)

// CorrelationHeader is the canonical header used to propagate a correlation id
// across all TradePulse services.
const CorrelationHeader = "X-Correlation-ID"

type ctxKey string

const correlationIDKey ctxKey = "correlation_id"

// NewCorrelationID returns a random hex identifier used when a request does not
// already carry a correlation id.
func NewCorrelationID() string {
	b := make([]byte, 16)
	if _, err := rand.Read(b); err != nil {
		return "unknown"
	}
	return hex.EncodeToString(b)
}

// CorrelationIDFromContext extracts the correlation id bound to the request
// context, or "-" when absent.
func CorrelationIDFromContext(ctx context.Context) string {
	if cid, ok := ctx.Value(correlationIDKey).(string); ok {
		return cid
	}
	return "-"
}

// CorrelationMiddleware ensures every request has a correlation id, binds it to
// the request context, and echoes it back on the response.
func CorrelationMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		cid := strings.TrimSpace(r.Header.Get(CorrelationHeader))
		if cid == "" {
			cid = NewCorrelationID()
		}
		w.Header().Set(CorrelationHeader, cid)
		ctx := context.WithValue(r.Context(), correlationIDKey, cid)
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}

type statusRecorder struct {
	http.ResponseWriter
	status int
}

func (s *statusRecorder) WriteHeader(code int) {
	s.status = code
	s.ResponseWriter.WriteHeader(code)
}

// Flush forwards to the underlying ResponseWriter when it supports flushing, so
// long-lived streaming responses (e.g. Server-Sent Events) work even though the
// handler is wrapped by the logging middleware. Without this, the wrapped
// writer would hide the http.Flusher the SSE handler relies on.
func (s *statusRecorder) Flush() {
	if f, ok := s.ResponseWriter.(http.Flusher); ok {
		f.Flush()
	}
}

// RequestLogger emits a structured log line per request, including the
// correlation id.
func RequestLogger(logger *slog.Logger, next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		rec := &statusRecorder{ResponseWriter: w, status: http.StatusOK}
		next.ServeHTTP(rec, r)
		logger.LogAttrs(r.Context(), slog.LevelInfo, "http_request",
			slog.String("correlation_id", CorrelationIDFromContext(r.Context())),
			slog.String("method", r.Method),
			slog.String("path", r.URL.Path),
			slog.Int("status", rec.status),
			slog.Duration("duration", time.Since(start)),
		)
	})
}

// WriteJSON writes a JSON response with the given status code.
func WriteJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

// HealthHandler returns a handler that reports service liveness as
// {"status":"UP","service":<serviceName>}.
func HealthHandler(serviceName string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		WriteJSON(w, http.StatusOK, map[string]string{
			"status":  "UP",
			"service": serviceName,
		})
	}
}

// RootHandler returns a handler for "/" that reports service metadata and
// responds 404 for any other unmatched path (the ServeMux "/" pattern is a
// catch-all).
func RootHandler(serviceName, version string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/" {
			WriteJSON(w, http.StatusNotFound, map[string]string{"error": "not_found"})
			return
		}
		WriteJSON(w, http.StatusOK, map[string]string{
			"service": serviceName,
			"version": version,
		})
	}
}

// Wrap applies the standard middleware chain (correlation id + request logging)
// around a handler.
func Wrap(logger *slog.Logger, next http.Handler) http.Handler {
	return CorrelationMiddleware(RequestLogger(logger, next))
}

// NewLogger builds a JSON slog.Logger bound to the service name, honoring the
// LOG_LEVEL environment variable (DEBUG enables debug logging).
func NewLogger(serviceName string) *slog.Logger {
	level := slog.LevelInfo
	if strings.EqualFold(os.Getenv("LOG_LEVEL"), "DEBUG") {
		level = slog.LevelDebug
	}
	handler := slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: level})
	return slog.New(handler).With(slog.String("service", serviceName))
}
