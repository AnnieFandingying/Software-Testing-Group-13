package main

import (
	"context"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"

	pb "github.com/GoogleCloudPlatform/microservices-demo/src/checkoutservice/genproto"
	money "github.com/GoogleCloudPlatform/microservices-demo/src/checkoutservice/money"
	"github.com/sirupsen/logrus"
	"go.opentelemetry.io/otel/trace"
	"google.golang.org/grpc"
	"google.golang.org/grpc/metadata"
)

const (
	cnyCurrency             = "CNY"
	headerOriginalTotal     = "x-boutique-original-total"
	headerFinalTotal        = "x-boutique-final-total"
	headerDiscountAmount    = "x-boutique-discount-amount"
	headerDiscountRule      = "x-boutique-discount-rule"
	defaultTelemetryTimeout = 100 * time.Millisecond
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

type discountDecision struct {
	ShouldCallService bool
	OriginalAmount    *pb.Money
	DiscountAmount    *pb.Money
	FinalAmount       *pb.Money
	AppliedRule       string
}

func discountDecisionForCurrency(currency string, original *pb.Money, resp *pb.GetDiscountResponse) discountDecision {
	if currency != cnyCurrency || resp == nil {
		return discountDecision{
			ShouldCallService: false,
			OriginalAmount:    original,
			DiscountAmount:    &pb.Money{CurrencyCode: currency},
			FinalAmount:       original,
			AppliedRule:       "NO_DISCOUNT",
		}
	}
	return discountDecision{
		ShouldCallService: true,
		OriginalAmount:    resp.GetOriginalAmount(),
		DiscountAmount:    resp.GetDiscountAmount(),
		FinalAmount:       resp.GetFinalAmount(),
		AppliedRule:       resp.GetAppliedRule(),
	}
}

func (cs *checkoutService) getDiscount(ctx context.Context, currency string, original *pb.Money) (discountDecision, error) {
	if currency != cnyCurrency {
		return discountDecisionForCurrency(currency, original, nil), nil
	}
	resp, err := pb.NewDiscountServiceClient(cs.discountSvcConn).GetDiscount(ctx, &pb.GetDiscountRequest{
		OriginalAmount: original,
		CurrencyCode:   currency,
	})
	if err != nil {
		return discountDecision{}, fmt.Errorf("failed to get discount: %+v", err)
	}
	return discountDecisionForCurrency(currency, original, resp), nil
}

func encodeMoneyHeader(amount *pb.Money) string {
	if amount == nil {
		return ""
	}
	return fmt.Sprintf("%s:%d:%d", amount.GetCurrencyCode(), amount.GetUnits(), amount.GetNanos())
}

func setCheckoutPricingHeaders(ctx context.Context, original, final, discount *pb.Money, rule string) {
	_ = grpc.SetHeader(ctx, metadata.Pairs(
		headerOriginalTotal, encodeMoneyHeader(original),
		headerFinalTotal, encodeMoneyHeader(final),
		headerDiscountAmount, encodeMoneyHeader(discount),
		headerDiscountRule, rule,
	))
}

func traceIDFromContext(ctx context.Context) string {
	span := trace.SpanContextFromContext(ctx)
	if !span.IsValid() {
		return ""
	}
	return span.TraceID().String()
}

func classifyCheckoutError(err error) string {
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

func moneyToFloat(amount *pb.Money) float64 {
	if amount == nil {
		return 0
	}
	return float64(amount.GetUnits()) + float64(amount.GetNanos())/1e9
}

func subtractMoney(l, r pb.Money) pb.Money {
	return money.Must(money.Sum(l, money.Negate(r)))
}

type httpTelemetryReporter struct {
	client *http.Client
	url    string
	log    *logrus.Logger
}

func (r *httpTelemetryReporter) ReportAsync(ctx context.Context, evt telemetryEvent) {
	if r == nil || r.url == "" {
		return
	}
	go reportTelemetry(ctx, r.client, r.url, r.log, evt)
}

func reportTelemetry(ctx context.Context, client *http.Client, url string, log *logrus.Logger, evt telemetryEvent) {
	if client == nil || url == "" {
		return
	}
	payload := []byte(fmt.Sprintf(`{"service":"%s","action":"%s","status":"%s","error_type":"%s","duration_ms":%d,"trace_id":"%s","original_total":%s,"discount_amount":%s,"final_total":%s,"discount_rule":"%s"}`,
		evt.Service,
		evt.Action,
		evt.Status,
		evt.ErrorType,
		evt.DurationMillis,
		evt.TraceID,
		strconv.FormatFloat(evt.OriginalTotal, 'f', -1, 64),
		strconv.FormatFloat(evt.DiscountAmount, 'f', -1, 64),
		strconv.FormatFloat(evt.FinalTotal, 'f', -1, 64),
		evt.DiscountRule,
	))
	reqCtx, cancel := context.WithTimeout(ctx, defaultTelemetryTimeout)
	defer cancel()
	req, err := http.NewRequestWithContext(reqCtx, http.MethodPost, url, strings.NewReader(string(payload)))
	if err != nil {
		log.WithError(err).Warn("failed to create telemetry request")
		return
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := client.Do(req)
	if err != nil {
		log.WithError(err).Warn("failed to send telemetry event")
		return
	}
	_ = resp.Body.Close()
}
