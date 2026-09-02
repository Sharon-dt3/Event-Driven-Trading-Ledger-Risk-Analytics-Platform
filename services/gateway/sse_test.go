package main

import (
	"bufio"
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

// TestSSEDeliversPublishedMessage verifies the broker -> SSE path: a message
// published to the broker is written to a connected /stream client with the
// correct event name and data payload.
func TestSSEDeliversPublishedMessage(t *testing.T) {
	broker := newBroker()
	srv := httptest.NewServer(sseHandler(broker))
	defer srv.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()

	req, _ := http.NewRequestWithContext(ctx, http.MethodGet, srv.URL, nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("connect: %v", err)
	}
	defer resp.Body.Close()

	if ct := resp.Header.Get("Content-Type"); !strings.HasPrefix(ct, "text/event-stream") {
		t.Fatalf("expected SSE content type, got %q", ct)
	}

	// Give the handler a moment to register the subscriber, then publish.
	deadline := time.Now().Add(time.Second)
	for broker.clientCount() == 0 && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
	}
	broker.publish(Message{Event: "ticks", Data: `{"symbol":"AAPL"}`})

	reader := bufio.NewReader(resp.Body)
	var gotEvent, gotData bool
	for i := 0; i < 20; i++ {
		line, err := reader.ReadString('\n')
		if err != nil {
			break
		}
		line = strings.TrimRight(line, "\r\n")
		if line == "event: ticks" {
			gotEvent = true
		}
		if line == `data: {"symbol":"AAPL"}` {
			gotData = true
		}
		if gotEvent && gotData {
			break
		}
	}
	if !gotEvent || !gotData {
		t.Fatalf("did not receive expected SSE event/data (event=%v data=%v)", gotEvent, gotData)
	}
}
