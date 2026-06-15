package main

import (
	"testing"

	pb "github.com/GoogleCloudPlatform/microservices-demo/src/frontend/genproto"
)

func TestApplyDisplayDiscount_SupportsFrontendCurrencyList(t *testing.T) {
	for _, currency := range []string{"EUR", "USD", "JPY", "GBP", "TRY", "CAD"} {
		total := pb.Money{CurrencyCode: currency, Units: 720}
		got := applyDisplayDiscount(currency, total)
		if got.GetUnits() != 520 {
			t.Fatalf("%s got units %d, want 520", currency, got.GetUnits())
		}
	}
}

func TestApplyDisplayDiscount_SkipsUnsupportedCurrency(t *testing.T) {
	total := pb.Money{CurrencyCode: "AUD", Units: 720}
	got := applyDisplayDiscount("AUD", total)
	if got.GetUnits() != 720 {
		t.Fatalf("got units %d, want 720", got.GetUnits())
	}
}
