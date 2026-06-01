package main

import (
	"context"
	"net/http"
	"strconv"
	"strings"
	"time"

	pb "github.com/GoogleCloudPlatform/microservices-demo/src/frontend/genproto"
	"github.com/sirupsen/logrus"
	"go.opentelemetry.io/otel/trace"
)

type telemetryEvent struct {
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

func traceIDFromContext(ctx context.Context) string {
	span := trace.SpanContextFromContext(ctx)
	if !span.IsValid() {
		return ""
	}
	return span.TraceID().String()
}

func decodeMoneyHeader(header http.Header, key string) *pb.Money {
	value := header.Get(key)
	if value == "" {
		return nil
	}
	parts := strings.Split(value, ":")
	if len(parts) != 3 {
		return nil
	}
	units, err := strconv.ParseInt(parts[1], 10, 64)
	if err != nil {
		return nil
	}
	nanos, err := strconv.ParseInt(parts[2], 10, 32)
	if err != nil {
		return nil
	}
	return &pb.Money{CurrencyCode: parts[0], Units: units, Nanos: int32(nanos)}
}

func classifyFrontendError(err error) string {
	if err == nil {
		return "none"
	}
	msg := strings.ToLower(err.Error())
	switch {
	case strings.Contains(msg, "timeout"):
		return "timeout"
	case strings.Contains(msg, "unavailable"):
		return "unavailable"
	default:
		return "internal"
	}
}

func (fe *frontendServer) sendTelemetryEvent(ctx context.Context, evt telemetryEvent) {
	if fe.telemetryServiceURL == "" || fe.telemetryClient == nil {
		return
	}
	go func() {
		reqCtx, cancel := context.WithTimeout(ctx, 100*time.Millisecond)
		defer cancel()
		body := strings.NewReader(`{"service":"` + evt.Service + `","action":"` + evt.Action + `","status":"` + evt.Status + `","error_type":"` + evt.ErrorType + `","duration_ms":` + strconv.FormatInt(evt.DurationMillis, 10) + `,"trace_id":"` + evt.TraceID + `"}`)
		req, err := http.NewRequestWithContext(reqCtx, http.MethodPost, fe.telemetryServiceURL, body)
		if err != nil {
			return
		}
		req.Header.Set("Content-Type", "application/json")
		resp, err := fe.telemetryClient.Do(req)
		if err != nil {
			return
		}
		_ = resp.Body.Close()
	}()
}

func (fe *frontendServer) logFrontendEvent(log logrus.FieldLogger, status string, duration time.Duration, err error) {
	log.WithFields(logrus.Fields{
		"event":       "http_request_received",
		"service":     "frontend",
		"action":      "place_order",
		"status":      status,
		"error_type":  classifyFrontendError(err),
		"duration_ms": duration.Milliseconds(),
	}).Info("frontend checkout event")
}
