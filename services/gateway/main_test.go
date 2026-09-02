package main

import (
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/tradepulse/common-go/httpkit"
)

func testRouter() http.Handler {
	return newRouter(slog.New(slog.NewJSONHandler(io.Discard, nil)))
}

func TestHealthEndpoint(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/health", nil)
	rec := httptest.NewRecorder()
	testRouter().ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
	var body map[string]string
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("invalid json: %v", err)
	}
	if body["status"] != "UP" {
		t.Fatalf("expected status UP, got %q", body["status"])
	}
}

func TestCorrelationIDGeneratedAndEchoed(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/health", nil)
	rec := httptest.NewRecorder()
	testRouter().ServeHTTP(rec, req)

	if got := rec.Header().Get(httpkit.CorrelationHeader); got == "" {
		t.Fatalf("expected %s header to be set", httpkit.CorrelationHeader)
	}
}
