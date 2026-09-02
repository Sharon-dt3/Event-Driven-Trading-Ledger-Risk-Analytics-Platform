package main

import (
	"os"
	"strconv"
	"strings"
	"time"
)

// config holds the runtime configuration for the market-data service. All
// values are sourced from environment variables with sensible defaults so the
// service runs out-of-the-box (synthetic ticks) in local and CI environments.
type config struct {
	port          string
	redisAddr     string
	stream        string
	streamMaxLen  int64
	symbols       []string
	tickInterval  time.Duration
	source        string
	finnhubAPIKey string
}

func loadConfig() config {
	c := config{
		port:          getenv("PORT", "8081"),
		redisAddr:     getenv("REDIS_ADDR", "localhost:6379"),
		stream:        getenv("MARKET_DATA_STREAM", "market.ticks"),
		streamMaxLen:  getenvInt64("MARKET_DATA_STREAM_MAXLEN", 100000),
		symbols:       parseSymbols(getenv("MARKET_DATA_SYMBOLS", "AAPL,MSFT,GOOG")),
		tickInterval:  time.Duration(getenvInt64("MARKET_DATA_TICK_INTERVAL_MS", 1000)) * time.Millisecond,
		source:        strings.ToLower(strings.TrimSpace(getenv("MARKET_DATA_SOURCE", "synthetic"))),
		finnhubAPIKey: os.Getenv("FINNHUB_API_KEY"),
	}
	if c.tickInterval <= 0 {
		c.tickInterval = time.Second
	}
	if len(c.symbols) == 0 {
		c.symbols = []string{"AAPL"}
	}
	return c
}

func getenv(key, def string) string {
	if v := strings.TrimSpace(os.Getenv(key)); v != "" {
		return v
	}
	return def
}

func getenvInt64(key string, def int64) int64 {
	if v := strings.TrimSpace(os.Getenv(key)); v != "" {
		if n, err := strconv.ParseInt(v, 10, 64); err == nil {
			return n
		}
	}
	return def
}

func parseSymbols(raw string) []string {
	parts := strings.Split(raw, ",")
	out := make([]string, 0, len(parts))
	for _, p := range parts {
		s := strings.ToUpper(strings.TrimSpace(p))
		if s != "" {
			out = append(out, s)
		}
	}
	return out
}
