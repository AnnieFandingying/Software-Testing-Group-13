package main

import (
	"testing"

	pb "github.com/GoogleCloudPlatform/microservices-demo/src/discountservice/genproto"
)

func TestEvaluateDiscount_AppliesHighestMatchingRule(t *testing.T) {
	resp, err := evaluateDiscount(&pb.Money{CurrencyCode: cnyCurrency, Units: 720})
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

func TestEvaluateDiscount_SkipsNonCNY(t *testing.T) {
	resp, err := evaluateDiscount(&pb.Money{CurrencyCode: "USD", Units: 720})
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
