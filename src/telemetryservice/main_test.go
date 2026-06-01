package main

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestMetricsStore_NormalizesHighCardinalityFieldsOutOfLabels(t *testing.T) {
	store := newMetricsStore()
	store.record(Event{
		Service:        "frontend",
		Action:         "place_order",
		Status:         "ok",
		ErrorType:      "none",
		DurationMillis: 12,
		TraceID:        "trace-123",
		OriginalTotal:  420,
	})

	metrics := store.metricsText()
	if strings.Contains(metrics, "trace-123") {
		t.Fatalf("metrics unexpectedly included high-cardinality trace id")
	}
	if !strings.Contains(metrics, `service="frontend",action="place_order",status="ok",error_type="none"`) {
		t.Fatalf("metrics missing normalized labels: %s", metrics)
	}
}

func TestEventsHandler_AcceptsValidJSONWithAcceptedStatus(t *testing.T) {
	store := newMetricsStore()
	req := httptest.NewRequest(http.MethodPost, "/events", strings.NewReader(`{"service":"checkoutservice","action":"place_order","status":"ok","error_type":"none","duration_ms":18}`))
	rec := httptest.NewRecorder()

	eventsHandler(store).ServeHTTP(rec, req)

	if got, want := rec.Code, http.StatusAccepted; got != want {
		t.Fatalf("got status %d, want %d", got, want)
	}
}
