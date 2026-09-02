package main

import (
	"encoding/json"
	"regexp"
	"testing"
)

var uuidRe = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`)

func TestNewUUIDFormat(t *testing.T) {
	for i := 0; i < 50; i++ {
		u := newUUID()
		if !uuidRe.MatchString(u) {
			t.Fatalf("invalid uuid v4: %q", u)
		}
	}
}

func TestNewTickEnvelopeMatchesContract(t *testing.T) {
	env := newTickEnvelope("AAPL", 187.42, 120, sourceSynthetic, newUUID())

	if env.EventType != "TickReceived" {
		t.Fatalf("event_type = %q", env.EventType)
	}
	if env.SchemaVersion != "1" {
		t.Fatalf("schema_version = %q", env.SchemaVersion)
	}
	if env.Producer != serviceName {
		t.Fatalf("producer = %q", env.Producer)
	}
	if env.Data.Price <= 0 {
		t.Fatalf("price must be > 0, got %v", env.Data.Price)
	}
	if env.Data.Source != "synthetic" {
		t.Fatalf("source = %q", env.Data.Source)
	}
	if !uuidRe.MatchString(env.EventID) {
		t.Fatalf("event_id not a uuid: %q", env.EventID)
	}

	b, err := json.Marshal(env)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	var m map[string]any
	if err := json.Unmarshal(b, &m); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	for _, k := range []string{"event_id", "event_type", "schema_version", "correlation_id", "produced_at", "producer", "data"} {
		if _, ok := m[k]; !ok {
			t.Fatalf("missing envelope key %q", k)
		}
	}
}

func TestSyntheticSourceProducesPositivePrices(t *testing.T) {
	src := newSyntheticSource([]string{"AAPL", "ZZZZ"})
	for i := 0; i < 100; i++ {
		p, v := src.Next("AAPL")
		if p <= 0 {
			t.Fatalf("price must stay > 0, got %v", p)
		}
		if v < 0 {
			t.Fatalf("volume must be >= 0, got %v", v)
		}
	}
	if p, _ := src.Next("ZZZZ"); p <= 0 {
		t.Fatalf("unknown symbol should seed positive, got %v", p)
	}
}
