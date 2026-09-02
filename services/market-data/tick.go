package main

import (
	crand "crypto/rand"
	"fmt"
	"math"
	"math/rand"
	"time"
)

const (
	eventTypeTick   = "TickReceived"
	schemaVersion   = "1"
	sourceSynthetic = "synthetic"
	sourceFinnhub   = "finnhub"
)

// Envelope mirrors docs/contracts/events/envelope.schema.json specialized for
// TickReceived.v1 (data payload matches tick_received.v1.schema.json).
type Envelope struct {
	EventID       string   `json:"event_id"`
	EventType     string   `json:"event_type"`
	SchemaVersion string   `json:"schema_version"`
	CorrelationID string   `json:"correlation_id"`
	ProducedAt    string   `json:"produced_at"`
	Producer      string   `json:"producer"`
	Data          TickData `json:"data"`
}

// TickData is the TickReceived.v1 payload.
type TickData struct {
	Symbol   string  `json:"symbol"`
	Price    float64 `json:"price"`
	Volume   int64   `json:"volume"`
	Source   string  `json:"source"`
	TickTime string  `json:"tick_time"`
}

// newUUID returns an RFC 4122 version-4 UUID string using crypto/rand. The
// contract requires event_id and correlation_id to be UUID-formatted.
func newUUID() string {
	b := make([]byte, 16)
	if _, err := crand.Read(b); err != nil {
		return "00000000-0000-4000-8000-000000000000"
	}
	b[6] = (b[6] & 0x0f) | 0x40 // version 4
	b[8] = (b[8] & 0x3f) | 0x80 // variant 10
	return fmt.Sprintf("%x-%x-%x-%x-%x", b[0:4], b[4:6], b[6:8], b[8:10], b[10:16])
}

// newTickEnvelope builds a contract-valid TickReceived.v1 envelope. produced_at
// and tick_time are RFC3339 UTC timestamps.
func newTickEnvelope(symbol string, price float64, volume int64, source, correlationID string) Envelope {
	now := time.Now().UTC().Format(time.RFC3339Nano)
	return Envelope{
		EventID:       newUUID(),
		EventType:     eventTypeTick,
		SchemaVersion: schemaVersion,
		CorrelationID: correlationID,
		ProducedAt:    now,
		Producer:      serviceName,
		Data: TickData{
			Symbol:   symbol,
			Price:    price,
			Volume:   volume,
			Source:   source,
			TickTime: now,
		},
	}
}

// SyntheticSource generates deterministic-seed, random-walk prices per symbol.
// Prices always stay strictly positive to satisfy the contract (price > 0).
type SyntheticSource struct {
	symbols []string
	last    map[string]float64
	rng     *rand.Rand
}

func newSyntheticSource(symbols []string) *SyntheticSource {
	last := make(map[string]float64, len(symbols))
	for _, s := range symbols {
		last[s] = seedPrice(s)
	}
	return &SyntheticSource{
		symbols: symbols,
		last:    last,
		rng:     rand.New(rand.NewSource(time.Now().UnixNano())),
	}
}

func seedPrice(symbol string) float64 {
	base := map[string]float64{
		"AAPL": 187.0,
		"MSFT": 415.0,
		"GOOG": 152.0,
		"AMZN": 178.0,
		"TSLA": 245.0,
	}
	if p, ok := base[symbol]; ok {
		return p
	}
	return 100.0
}

// Next advances the price for a symbol by up to +/-0.5% and returns a new
// (price, volume) pair. Price is rounded to cents and kept > 0.
func (s *SyntheticSource) Next(symbol string) (price float64, volume int64) {
	prev, ok := s.last[symbol]
	if !ok || prev <= 0 {
		prev = seedPrice(symbol)
	}
	pct := (s.rng.Float64() - 0.5) / 100.0 // [-0.5%, +0.5%]
	next := prev * (1 + pct)
	if next <= 0 {
		next = prev
	}
	next = math.Round(next*100) / 100
	s.last[symbol] = next
	volume = int64(s.rng.Intn(1000) + 1)
	return next, volume
}
