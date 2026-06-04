package main

import (
	"testing"

	pb "github.com/GoogleCloudPlatform/microservices-demo/src/checkoutservice/genproto"
)

func TestDiscountDecisionForCurrency_SkipsNonCNY(t *testing.T) {
	decision := discountDecisionForCurrency("USD", &pb.Money{CurrencyCode: "USD", Units: 420}, nil)
	if decision.ShouldCallService {
		t.Fatalf("expected non-CNY checkout to skip discount service")
	}
	if decision.FinalAmount.GetUnits() != 420 {
		t.Fatalf("expected original amount to flow through unchanged")
	}
}
