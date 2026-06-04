package main

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestDecodeMoneyHeader_ParsesUnits(t *testing.T) {
	header := http.Header{}
	header.Set("x-boutique-final-total", "CNY:320:0")

	money := decodeMoneyHeader(header, "x-boutique-final-total")
	if money == nil {
		t.Fatal("expected money value")
	}
	if got, want := money.GetUnits(), int64(320); got != want {
		t.Fatalf("got units %d, want %d", got, want)
	}
}

func TestSendTelemetryEvent_ReturnsEarlyWithoutURL(t *testing.T) {
	req := httptest.NewRequest(http.MethodPost, "/", nil)
	server := &frontendServer{}
	server.sendTelemetryEvent(req.Context(), telemetryEvent{})
}
