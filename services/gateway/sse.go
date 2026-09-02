package main

import (
	"fmt"
	"net/http"
	"time"
)

// sseHandler streams broker messages to a browser EventSource. It sets the
// Server-Sent Events content type, disables proxy buffering, and emits periodic
// keep-alive comments so idle connections (and intermediary proxies) stay open.
func sseHandler(broker *Broker) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		flusher, ok := w.(http.Flusher)
		if !ok {
			http.Error(w, "streaming unsupported", http.StatusInternalServerError)
			return
		}

		h := w.Header()
		h.Set("Content-Type", "text/event-stream")
		h.Set("Cache-Control", "no-cache")
		h.Set("Connection", "keep-alive")
		h.Set("X-Accel-Buffering", "no") // disable nginx proxy buffering for SSE
		h.Set("Access-Control-Allow-Origin", "*")

		ch := broker.subscribe()
		defer broker.unsubscribe(ch)

		// Open the stream so the client's onopen fires immediately.
		fmt.Fprint(w, ": connected\n\n")
		flusher.Flush()

		keepAlive := time.NewTicker(15 * time.Second)
		defer keepAlive.Stop()

		ctx := r.Context()
		for {
			select {
			case <-ctx.Done():
				return
			case msg, ok := <-ch:
				if !ok {
					return
				}
				fmt.Fprintf(w, "event: %s\ndata: %s\n\n", msg.Event, msg.Data)
				flusher.Flush()
			case <-keepAlive.C:
				fmt.Fprint(w, ": keep-alive\n\n")
				flusher.Flush()
			}
		}
	}
}
