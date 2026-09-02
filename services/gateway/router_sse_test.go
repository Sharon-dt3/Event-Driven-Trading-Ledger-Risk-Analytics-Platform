package main

import (
	"bufio"
	"context"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

// TestSSEFlushesThroughMiddlewareChain guards the exact bug the isolated broker
// test could not catch: when the SSE handler is served through the real router
// (httpkit.Wrap -> RequestLogger -> statusRecorder), the wrapping writer must
// still expose http.Flusher, or the handler responds "streaming unsupported"
// and no events ever reach the browser. This drives a real HTTP request through
// newRouter (the production chain) rather than calling sseHandler directly.
func TestSSEFlushesThroughMiddlewareChain(t *testing.T) {
	broker := newBroker()
	router := newRouter(slog.New(slog.NewJSONHandler(io.Discard, nil)), broker)
	srv := httptest.NewServer(router)
	defer srv.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()

	req, _ := http.NewRequestWithContext(ctx, http.MethodGet, srv.URL+"/stream", nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("connect: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Fatalf("expected 200 through middleware, got %d", resp.StatusCode)
	}
	if ct := resp.Header.Get("Content-Type"); !strings.HasPrefix(ct, "text/event-stream") {
		t.Fatalf("expected SSE content type, got %q", ct)
	}

	// Wait for the subscriber to register, then publish through the broker.
	deadline := time.Now().Add(time.Second)
	for broker.clientCount() == 0 && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
	}
	broker.publish(Message{Event: "ticks", Data: `{"symbol":"MSFT"}`})

	// If the middleware masks http.Flusher, the initial ": connected" preamble
	// and this event never flush and the read blocks until timeout.
	reader := bufio.NewReader(resp.Body)
	var gotEvent, gotData bool
	for i := 0; i < 30; i++ {
		line, err := reader.ReadString('\n')
		if err != nil {
			break
		}
		line = strings.TrimRight(line, "\r\n")
		if line == "event: ticks" {
			gotEvent = true
		}
		if line == `data: {"symbol":"MSFT"}` {
			gotData = true
		}
		if gotEvent && gotData {
			break
		}
	}
	if !gotEvent || !gotData {
		t.Fatalf("SSE did not flush through middleware chain (event=%v data=%v) — check statusRecorder.Flush", gotEvent, gotData)
	}
}
