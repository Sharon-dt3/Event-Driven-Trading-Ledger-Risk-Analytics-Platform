package main

import "sync"

// Message is a single Server-Sent Event: a logical event name (ticks|risk) and
// the raw envelope JSON payload to deliver as the SSE data field.
type Message struct {
	Event string
	Data  string
}

// Broker fans out stream messages to every connected SSE client. Each client is
// a buffered channel; when a client's buffer is full (a slow/stalled browser)
// the message is dropped for that client instead of blocking the whole feed.
type Broker struct {
	mu      sync.RWMutex
	clients map[chan Message]struct{}
}

func newBroker() *Broker {
	return &Broker{clients: make(map[chan Message]struct{})}
}

// subscribe registers a new client and returns its delivery channel.
func (b *Broker) subscribe() chan Message {
	ch := make(chan Message, 128)
	b.mu.Lock()
	b.clients[ch] = struct{}{}
	b.mu.Unlock()
	return ch
}

// unsubscribe removes a client and closes its channel.
func (b *Broker) unsubscribe(ch chan Message) {
	b.mu.Lock()
	if _, ok := b.clients[ch]; ok {
		delete(b.clients, ch)
		close(ch)
	}
	b.mu.Unlock()
}

// publish delivers a message to all subscribers without blocking on slow ones.
func (b *Broker) publish(msg Message) {
	b.mu.RLock()
	for ch := range b.clients {
		select {
		case ch <- msg:
		default:
			// Slow client: drop this message rather than stalling the fan-out.
		}
	}
	b.mu.RUnlock()
}

// clientCount reports the number of connected SSE clients (used in logs).
func (b *Broker) clientCount() int {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return len(b.clients)
}
