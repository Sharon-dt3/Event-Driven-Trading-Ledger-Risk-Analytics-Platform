package main

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"sync"
	"testing"
	"time"
)

type fakePublisher struct {
	mu     sync.Mutex
	stream string
	maxLen int64
	calls  []map[string]string
	err    error
}

func (f *fakePublisher) XAdd(_ context.Context, stream string, maxLen int64, fields map[string]string) (string, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.err != nil {
		return "", f.err
	}
	f.stream = stream
	f.maxLen = maxLen
	// copy to avoid aliasing
	cp := make(map[string]string, len(fields))
	for k, v := range fields {
		cp[k] = v
	}
	f.calls = append(f.calls, cp)
	return "1-0", nil
}

func testLogger() *slog.Logger {
	return slog.New(slog.NewJSONHandler(io.Discard, nil))
}

func TestPublishOnceEmitsOneTickPerSymbol(t *testing.T) {
	cfg := config{
		stream:       "market.ticks",
		streamMaxLen: 100000,
		symbols:      []string{"AAPL", "MSFT"},
		tickInterval: time.Second,
	}
	fp := &fakePublisher{}
	p := &Producer{
		cfg:    cfg,
		pub:    fp,
		src:    newSyntheticSource(cfg.symbols),
		source: sourceSynthetic,
		logger: testLogger(),
	}

	p.publishOnce(context.Background())

	if len(fp.calls) != 2 {
		t.Fatalf("expected 2 XADD calls, got %d", len(fp.calls))
	}
	if fp.stream != "market.ticks" {
		t.Fatalf("stream = %q", fp.stream)
	}
	if fp.maxLen != 100000 {
		t.Fatalf("maxLen = %d", fp.maxLen)
	}

	for _, call := range fp.calls {
		if call["event_type"] != "TickReceived" {
			t.Fatalf("event_type field = %q", call["event_type"])
		}
		if call["schema_version"] != "1" {
			t.Fatalf("schema_version field = %q", call["schema_version"])
		}
		raw, ok := call["event"]
		if !ok {
			t.Fatalf("missing 'event' field")
		}
		var env Envelope
		if err := json.Unmarshal([]byte(raw), &env); err != nil {
			t.Fatalf("event payload not valid json: %v", err)
		}
		if env.EventType != "TickReceived" || env.Data.Price <= 0 || env.Data.Source != "synthetic" {
			t.Fatalf("invalid envelope: %+v", env)
		}
	}
}

func TestResolveSourceFinnhubFallsBackToSynthetic(t *testing.T) {
	cfg := config{source: sourceFinnhub}
	if got := resolveSource(cfg, testLogger()); got != sourceSynthetic {
		t.Fatalf("expected synthetic fallback, got %q", got)
	}

	cfg = config{source: "weird"}
	if got := resolveSource(cfg, testLogger()); got != sourceSynthetic {
		t.Fatalf("expected synthetic fallback for unknown source, got %q", got)
	}

	cfg = config{source: sourceSynthetic}
	if got := resolveSource(cfg, testLogger()); got != sourceSynthetic {
		t.Fatalf("expected synthetic, got %q", got)
	}
}
