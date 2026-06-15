package main

import (
	"testing"

	pb "github.com/GoogleCloudPlatform/microservices-demo/src/discountservice/genproto"
)

func TestEvaluateDiscount_AppliesHighestMatchingRule(t *testing.T) {
	resp, err := evaluateDiscount(&pb.Money{CurrencyCode: "USD", Units: 720}, "USD")
	if err != nil {
		t.Fatal(err)
	}
	if got, want := resp.GetAppliedRule(), "FULL_700_MINUS_200"; got != want {
		t.Fatalf("got rule %q, want %q", got, want)
	}
	if got, want := resp.GetDiscountAmount().GetUnits(), int64(200); got != want {
		t.Fatalf("got discount %d, want %d", got, want)
	}
	if got, want := resp.GetFinalAmount().GetUnits(), int64(520); got != want {
		t.Fatalf("got final amount %d, want %d", got, want)
	}
}

func TestEvaluateDiscount_SupportsFrontendCurrencyList(t *testing.T) {
	for _, currency := range []string{"EUR", "USD", "JPY", "GBP", "TRY", "CAD"} {
		resp, err := evaluateDiscount(&pb.Money{CurrencyCode: currency, Units: 420}, currency)
		if err != nil {
			t.Fatal(err)
		}
		if got, want := resp.GetAppliedRule(), "FULL_400_MINUS_100"; got != want {
			t.Fatalf("%s got rule %q, want %q", currency, got, want)
		}
		if got, want := resp.GetDiscountAmount().GetCurrencyCode(), currency; got != want {
			t.Fatalf("%s got discount currency %q, want %q", currency, got, want)
		}
		if got, want := resp.GetFinalAmount().GetUnits(), int64(320); got != want {
			t.Fatalf("%s got final amount %d, want %d", currency, got, want)
		}
	}
}

func TestEvaluateDiscount_SkipsUnsupportedCurrency(t *testing.T) {
	resp, err := evaluateDiscount(&pb.Money{CurrencyCode: "AUD", Units: 720}, "AUD")
	if err != nil {
		t.Fatal(err)
	}
	if got, want := resp.GetAppliedRule(), "NO_DISCOUNT"; got != want {
		t.Fatalf("got rule %q, want %q", got, want)
	}
	if got, want := resp.GetDiscountAmount().GetUnits(), int64(0); got != want {
		t.Fatalf("got discount %d, want %d", got, want)
	}
	if got, want := resp.GetFinalAmount().GetUnits(), int64(720); got != want {
		t.Fatalf("got final amount %d, want %d", got, want)
	}
}

func TestEvaluateDiscount_UsesRequestedCurrencyWhenMoneyCurrencyIsMissing(t *testing.T) {
	resp, err := evaluateDiscount(&pb.Money{Units: 420}, "USD")
	if err != nil {
		t.Fatal(err)
	}
	if got, want := resp.GetAppliedRule(), "FULL_400_MINUS_100"; got != want {
		t.Fatalf("got rule %q, want %q", got, want)
	}
	if got, want := resp.GetOriginalAmount().GetCurrencyCode(), "USD"; got != want {
		t.Fatalf("got original currency %q, want %q", got, want)
	}
	if got, want := resp.GetFinalAmount().GetUnits(), int64(320); got != want {
		t.Fatalf("got final amount %d, want %d", got, want)
	}
}
