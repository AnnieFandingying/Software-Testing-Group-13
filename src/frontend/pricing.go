package main

import (
	pb "github.com/GoogleCloudPlatform/microservices-demo/src/frontend/genproto"
	"github.com/GoogleCloudPlatform/microservices-demo/src/frontend/money"
)

func applyDisplayDiscount(currency string, total pb.Money) pb.Money {
	if currency != "CNY" {
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
