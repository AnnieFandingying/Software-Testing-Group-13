package main

import (
	"testing"

	pb "github.com/GoogleCloudPlatform/microservices-demo/src/checkoutservice/genproto"
)

func TestDiscountDecisionForCurrency_UsesSupportedUICurrency(t *testing.T) {
	decision := discountDecisionForCurrency(
		"USD",
		&pb.Money{CurrencyCode: "USD", Units: 420},
		&pb.GetDiscountResponse{
			OriginalAmount: &pb.Money{CurrencyCode: "USD", Units: 420},
			DiscountAmount: &pb.Money{CurrencyCode: "USD", Units: 100},
			FinalAmount:    &pb.Money{CurrencyCode: "USD", Units: 320},
			AppliedRule:    "FULL_400_MINUS_100",
		},
	)
	if !decision.ShouldCallService {
		t.Fatalf("expected supported UI currency checkout to use discount service")
	}
	if decision.FinalAmount.GetUnits() != 320 {
		t.Fatalf("expected discounted final amount")
	}
}

func TestDiscountDecisionForCurrency_SkipsUnsupportedCurrency(t *testing.T) {
	decision := discountDecisionForCurrency("AUD", &pb.Money{CurrencyCode: "AUD", Units: 420}, nil)
	if decision.ShouldCallService {
		t.Fatalf("expected unsupported currency checkout to skip discount service")
	}
	if decision.FinalAmount.GetUnits() != 420 {
		t.Fatalf("expected original amount to flow through unchanged")
	}
}

func TestIsDiscountCurrency_SupportsFrontendCurrencyList(t *testing.T) {
	for _, currency := range []string{"EUR", "USD", "JPY", "GBP", "TRY", "CAD"} {
		if !isDiscountCurrency(currency) {
			t.Fatalf("expected %s to be discount-enabled", currency)
		}
	}
}
