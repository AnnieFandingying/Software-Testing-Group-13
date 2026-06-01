package main

import (
	"context"
	"fmt"
	"net/http"
	"time"

	pb "github.com/GoogleCloudPlatform/microservices-demo/src/discountservice/genproto"
	"github.com/sirupsen/logrus"
)

const cnyCurrency = "CNY"

type discountRule struct {
	Threshold int64
	Discount  int64
	Code      string
}

var discountRules = []discountRule{
	{Threshold: 700, Discount: 200, Code: "FULL_700_MINUS_200"},
	{Threshold: 400, Discount: 100, Code: "FULL_400_MINUS_100"},
	{Threshold: 200, Discount: 50, Code: "FULL_200_MINUS_50"},
}

type telemetryReporter interface {
	ReportAsync(telemetryEvent)
}

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

type discountServer struct {
	pb.UnimplementedDiscountServiceServer
	log       *logrus.Logger
	telemetry telemetryReporter
}

func evaluateDiscount(amount *pb.Money) (*pb.GetDiscountResponse, error) {
	if amount == nil {
		return nil, fmt.Errorf("amount is required")
	}
	if amount.GetCurrencyCode() != cnyCurrency {
		zero := &pb.Money{CurrencyCode: amount.GetCurrencyCode()}
		return &pb.GetDiscountResponse{
			OriginalAmount: amount,
			DiscountAmount: zero,
			FinalAmount:    amount,
			AppliedRule:    "NO_DISCOUNT",
			Description:    "discount skipped for non-CNY currency",
		}, nil
	}

	finalUnits := amount.GetUnits()
	discountUnits := int64(0)
	ruleCode := "NO_DISCOUNT"
	for _, rule := range discountRules {
		if finalUnits >= rule.Threshold {
			discountUnits = rule.Discount
			ruleCode = rule.Code
			break
		}
	}

	finalUnits -= discountUnits
	return &pb.GetDiscountResponse{
		OriginalAmount: amount,
		DiscountAmount: &pb.Money{CurrencyCode: amount.GetCurrencyCode(), Units: discountUnits},
		FinalAmount:    &pb.Money{CurrencyCode: amount.GetCurrencyCode(), Units: finalUnits},
		AppliedRule:    ruleCode,
		Description:    fmt.Sprintf("applied %s", ruleCode),
	}, nil
}

func (s *discountServer) GetDiscount(ctx context.Context, req *pb.GetDiscountRequest) (*pb.GetDiscountResponse, error) {
	start := time.Now()
	resp, err := evaluateDiscount(req.GetOriginalAmount())
	status := "ok"
	errorType := "none"
	if err != nil {
		status = "error"
		errorType = "bad_request"
	} else if resp.GetOriginalAmount() != nil {
		s.log.WithFields(logrus.Fields{
			"event":           "discount_calculated",
			"service":         "discountservice",
			"action":          "calculate_discount",
			"status":          status,
			"duration_ms":     time.Since(start).Milliseconds(),
			"rule":            resp.GetAppliedRule(),
			"original_amount": resp.GetOriginalAmount().GetUnits(),
			"discount_amount": resp.GetDiscountAmount().GetUnits(),
			"final_amount":    resp.GetFinalAmount().GetUnits(),
		}).Info("discount calculation completed")
	}
	if s.telemetry != nil && resp != nil {
		s.telemetry.ReportAsync(telemetryEvent{
			Service:        "discountservice",
			Action:         "calculate_discount",
			Status:         status,
			ErrorType:      errorType,
			DurationMillis: time.Since(start).Milliseconds(),
			OriginalTotal:  float64(resp.GetOriginalAmount().GetUnits()),
			DiscountAmount: float64(resp.GetDiscountAmount().GetUnits()),
			FinalTotal:     float64(resp.GetFinalAmount().GetUnits()),
			DiscountRule:   resp.GetAppliedRule(),
		})
	}
	return resp, err
}

type noopTelemetryReporter struct{}

func (noopTelemetryReporter) ReportAsync(telemetryEvent) {}

type httpTelemetryReporter struct {
	client *http.Client
	url    string
	log    *logrus.Logger
}
