package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"sort"
	"strings"
	"sync"
	"syscall"
	"time"
)

const (
	telemetryPort = "8080"
)

var (
	allowedServices = map[string]struct{}{"frontend": {}, "checkoutservice": {}, "discountservice": {}}
	allowedStatuses = map[string]struct{}{"ok": {}, "error": {}}
)

type Event struct {
	Service        string  `json:"service"`
	Action         string  `json:"action"`
	Status         string  `json:"status"`
	ErrorType      string  `json:"error_type"`
	DurationMillis int64   `json:"duration_ms"`
	TraceID        string  `json:"trace_id,omitempty"`
	OriginalTotal  float64 `json:"original_total,omitempty"`
	DiscountAmount float64 `json:"discount_amount,omitempty"`
	FinalTotal     float64 `json:"final_total,omitempty"`
	DiscountRule   string  `json:"discount_rule,omitempty"`
}

type metricKey struct {
	Service   string
	Action    string
	Status    string
	ErrorType string
}

type metricsStore struct {
	mu               sync.RWMutex
	requests         map[metricKey]int64
	errors           map[metricKey]int64
	durationSumMs    map[metricKey]int64
	discountHits     map[string]int64
	discountAmount   map[string]float64
	allowedActions   map[string]struct{}
	allowedErrTypes  map[string]struct{}
}

func newMetricsStore() *metricsStore {
	return &metricsStore{
		requests:        make(map[metricKey]int64),
		errors:          make(map[metricKey]int64),
		durationSumMs:   make(map[metricKey]int64),
		discountHits:    make(map[string]int64),
		discountAmount:  make(map[string]float64),
		allowedActions:  map[string]struct{}{"place_order": {}, "calculate_discount": {}, "http_request_received": {}, "checkout_completed": {}, "checkout_failed": {}},
		allowedErrTypes: map[string]struct{}{"none": {}, "timeout": {}, "unavailable": {}, "internal": {}, "bad_request": {}},
	}
}

func (s *metricsStore) normalizeKey(evt Event) metricKey {
	service := evt.Service
	if _, ok := allowedServices[service]; !ok {
		service = "unknown"
	}
	action := evt.Action
	if _, ok := s.allowedActions[action]; !ok {
		action = "other"
	}
	status := evt.Status
	if _, ok := allowedStatuses[status]; !ok {
		status = "error"
	}
	errType := evt.ErrorType
	if _, ok := s.allowedErrTypes[errType]; !ok {
		errType = "other"
	}
	return metricKey{Service: service, Action: action, Status: status, ErrorType: errType}
}

func (s *metricsStore) record(evt Event) {
	s.mu.Lock()
	defer s.mu.Unlock()

	key := s.normalizeKey(evt)
	s.requests[key]++
	s.durationSumMs[key] += evt.DurationMillis
	if key.Status == "error" {
		s.errors[key]++
	}
	if evt.Service == "discountservice" && evt.DiscountRule != "" {
		s.discountHits[evt.DiscountRule]++
		s.discountAmount[evt.DiscountRule] += evt.DiscountAmount
	}
}

func (s *metricsStore) metricsText() string {
	s.mu.RLock()
	defer s.mu.RUnlock()

	lines := []string{
		"# HELP boutique_requests_total Total processed telemetry events.",
		"# TYPE boutique_requests_total counter",
	}
	keys := make([]metricKey, 0, len(s.requests))
	for key := range s.requests {
		keys = append(keys, key)
	}
	sort.Slice(keys, func(i, j int) bool {
		return fmt.Sprintf("%v", keys[i]) < fmt.Sprintf("%v", keys[j])
	})
	for _, key := range keys {
		labels := fmt.Sprintf(`service="%s",action="%s",status="%s",error_type="%s"`, key.Service, key.Action, key.Status, key.ErrorType)
		lines = append(lines, fmt.Sprintf("boutique_requests_total{%s} %d", labels, s.requests[key]))
	}

	lines = append(lines,
		"# HELP boutique_errors_total Total processed error events.",
		"# TYPE boutique_errors_total counter",
	)
	for _, key := range keys {
		if count := s.errors[key]; count > 0 {
			labels := fmt.Sprintf(`service="%s",action="%s",status="%s",error_type="%s"`, key.Service, key.Action, key.Status, key.ErrorType)
			lines = append(lines, fmt.Sprintf("boutique_errors_total{%s} %d", labels, count))
		}
	}

	lines = append(lines,
		"# HELP boutique_request_duration_ms_sum Sum of request durations in milliseconds.",
		"# TYPE boutique_request_duration_ms_sum counter",
	)
	for _, key := range keys {
		labels := fmt.Sprintf(`service="%s",action="%s",status="%s",error_type="%s"`, key.Service, key.Action, key.Status, key.ErrorType)
		lines = append(lines, fmt.Sprintf("boutique_request_duration_ms_sum{%s} %d", labels, s.durationSumMs[key]))
	}

	lines = append(lines,
		"# HELP boutique_discount_hits_total Total discount rule hits.",
		"# TYPE boutique_discount_hits_total counter",
	)
	rules := make([]string, 0, len(s.discountHits))
	for rule := range s.discountHits {
		rules = append(rules, rule)
	}
	sort.Strings(rules)
	for _, rule := range rules {
		lines = append(lines, fmt.Sprintf(`boutique_discount_hits_total{rule="%s"} %d`, rule, s.discountHits[rule]))
	}

	lines = append(lines,
		"# HELP boutique_discount_amount_total Total discount amount aggregated by rule.",
		"# TYPE boutique_discount_amount_total counter",
	)
	for _, rule := range rules {
		lines = append(lines, fmt.Sprintf(`boutique_discount_amount_total{rule="%s"} %.0f`, rule, s.discountAmount[rule]))
	}

	return strings.Join(lines, "\n") + "\n"
}

func eventsHandler(store *metricsStore) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		defer r.Body.Close()
		var evt Event
		if err := json.NewDecoder(r.Body).Decode(&evt); err != nil {
			http.Error(w, "invalid json", http.StatusBadRequest)
			return
		}

		w.WriteHeader(http.StatusAccepted)
		store.record(evt)
	}
}

func metricsHandler(store *metricsStore) http.HandlerFunc {
	return func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "text/plain; version=0.0.4")
		_, _ = w.Write([]byte(store.metricsText()))
	}
}

func main() {
	store := newMetricsStore()
	mux := http.NewServeMux()
	mux.Handle("/events", eventsHandler(store))
	mux.Handle("/metrics", metricsHandler(store))
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, _ *http.Request) { _, _ = w.Write([]byte("ok")) })

	port := os.Getenv("PORT")
	if port == "" {
		port = telemetryPort
	}
	srv := &http.Server{
		Addr:    ":" + port,
		Handler: mux,
	}

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGTERM, syscall.SIGINT)
	defer stop()
	go func() {
		<-ctx.Done()
		time.Sleep(2 * time.Second)
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
		defer cancel()
		_ = srv.Shutdown(shutdownCtx)
	}()

	log.Printf("telemetryservice listening on %s", srv.Addr)
	if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Fatal(err)
	}
}
