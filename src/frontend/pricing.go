package main

import (
	"strings"

	pb "github.com/GoogleCloudPlatform/microservices-demo/src/frontend/genproto"
	"github.com/GoogleCloudPlatform/microservices-demo/src/frontend/money"
)

var discountCurrencies = map[string]struct{}{
	"EUR": {},
	"USD": {},
	"JPY": {},
	"GBP": {},
	"TRY": {},
	"CAD": {},
}

func applyDisplayDiscount(currency string, total pb.Money) pb.Money {
	if !isDiscountCurrency(currency) {
		return total
	}
	discount := pb.Money{CurrencyCode: currency}
	switch {
	case total.GetUnits() >= 700:
		discount.Units = 200
	case total.GetUnits() >= 400:
		discount.Units = 100
	case total.GetUnits() >= 200:
		discount.Units = 50
	default:
		return total
	}
	return money.Must(money.Sum(total, money.Negate(discount)))
}

func isDiscountCurrency(currency string) bool {
	_, ok := discountCurrencies[strings.ToUpper(currency)]
	return ok
}
