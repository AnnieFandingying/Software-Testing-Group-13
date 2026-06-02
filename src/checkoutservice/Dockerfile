# Copyright 2020 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

FROM golang:1.23.1-alpine@sha256:ac67716dd016429be8d4c2c53a248d7bcdf06d34127d3dc451bda6aa5a87bc06 AS builder
WORKDIR /src

RUN apk add --no-cache protobuf
RUN GOBIN=/usr/local/bin go install google.golang.org/protobuf/cmd/protoc-gen-go@v1.35.1
RUN GOBIN=/usr/local/bin go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@v1.5.1

# restore dependencies
COPY go.mod go.sum ./
RUN go mod download

COPY . .

RUN rm -f genproto/discount.pb.go \
 && cat > /tmp/demo.proto <<'PROTOEOF'
// Copyright 2020 Google LLC
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

syntax = "proto3";

package hipstershop;

option go_package = "github.com/GoogleCloudPlatform/microservices-demo/src/checkoutservice/genproto;hipstershop";

service CartService {
    rpc AddItem(AddItemRequest) returns (Empty) {}
    rpc GetCart(GetCartRequest) returns (Cart) {}
    rpc EmptyCart(EmptyCartRequest) returns (Empty) {}
}

message CartItem {
    string product_id = 1;
    int32 quantity = 2;
}

message AddItemRequest {
    string user_id = 1;
    CartItem item = 2;
}

message EmptyCartRequest {
    string user_id = 1;
}

message GetCartRequest {
    string user_id = 1;
}

message Cart {
    string user_id = 1;
    repeated CartItem items = 2;
}

message Empty {}

service RecommendationService {
    rpc ListRecommendations(ListRecommendationsRequest) returns (ListRecommendationsResponse) {}
}

message ListRecommendationsRequest {
    string user_id = 1;
    repeated string product_ids = 2;
}

message ListRecommendationsResponse {
    repeated string product_ids = 1;
}

service ProductCatalogService {
    rpc ListProducts(Empty) returns (ListProductsResponse) {}
    rpc GetProduct(GetProductRequest) returns (Product) {}
    rpc SearchProducts(SearchProductsRequest) returns (SearchProductsResponse) {}
}

message Product {
    string id = 1;
    string name = 2;
    string description = 3;
    string picture = 4;
    Money price_usd = 5;
    repeated string categories = 6;
}

message ListProductsResponse {
    repeated Product products = 1;
}

message GetProductRequest {
    string id = 1;
}

message SearchProductsRequest {
    string query = 1;
}

message SearchProductsResponse {
    repeated Product results = 1;
}

service ShippingService {
    rpc GetQuote(GetQuoteRequest) returns (GetQuoteResponse) {}
    rpc ShipOrder(ShipOrderRequest) returns (ShipOrderResponse) {}
}

message GetQuoteRequest {
    Address address = 1;
    repeated CartItem items = 2;
}

message GetQuoteResponse {
    Money cost_usd = 1;
}

message ShipOrderRequest {
    Address address = 1;
    repeated CartItem items = 2;
}

message ShipOrderResponse {
    string tracking_id = 1;
}

message Address {
    string street_address = 1;
    string city = 2;
    string state = 3;
    string country = 4;
    int32 zip_code = 5;
}

service CurrencyService {
    rpc GetSupportedCurrencies(Empty) returns (GetSupportedCurrenciesResponse) {}
    rpc Convert(CurrencyConversionRequest) returns (Money) {}
}

message Money {
    string currency_code = 1;
    int64 units = 2;
    int32 nanos = 3;
}

message GetSupportedCurrenciesResponse {
    repeated string currency_codes = 1;
}

message CurrencyConversionRequest {
    Money from = 1;
    string to_code = 2;
}

service PaymentService {
    rpc Charge(ChargeRequest) returns (ChargeResponse) {}
}

message CreditCardInfo {
    string credit_card_number = 1;
    int32 credit_card_cvv = 2;
    int32 credit_card_expiration_year = 3;
    int32 credit_card_expiration_month = 4;
}

message ChargeRequest {
    Money amount = 1;
    CreditCardInfo credit_card = 2;
}

message ChargeResponse {
    string transaction_id = 1;
}

service EmailService {
    rpc SendOrderConfirmation(SendOrderConfirmationRequest) returns (Empty) {}
}

message OrderItem {
    CartItem item = 1;
    Money cost = 2;
}

message OrderResult {
    string order_id = 1;
    string shipping_tracking_id = 2;
    Money shipping_cost = 3;
    Address shipping_address = 4;
    repeated OrderItem items = 5;
}

message SendOrderConfirmationRequest {
    string email = 1;
    OrderResult order = 2;
}

service CheckoutService {
    rpc PlaceOrder(PlaceOrderRequest) returns (PlaceOrderResponse) {}
}

message PlaceOrderRequest {
    string user_id = 1;
    string user_currency = 2;
    Address address = 3;
    string email = 5;
    CreditCardInfo credit_card = 6;
}

message PlaceOrderResponse {
    OrderResult order = 1;
}

service DiscountService {
    rpc GetDiscount(GetDiscountRequest) returns (GetDiscountResponse) {}
}

message GetDiscountRequest {
    Money original_amount = 1;
    string currency_code = 2;
}

message GetDiscountResponse {
    Money original_amount = 1;
    Money discount_amount = 2;
    Money final_amount = 3;
    string applied_rule = 4;
    string description = 5;
}

service AdService {
    rpc GetAds(AdRequest) returns (AdResponse) {}
}

message AdRequest {
    repeated string context_keys = 1;
}

message AdResponse {
    repeated Ad ads = 1;
}

message Ad {
    string redirect_url = 1;
    string text = 2;
}
PROTOEOF

RUN protoc --proto_path=/tmp \
  --go_out=./genproto \
  --go_opt=paths=source_relative \
  --go-grpc_out=./genproto \
  --go-grpc_opt=paths=source_relative \
  /tmp/demo.proto

# Skaffold passes in debug-oriented compiler flags
ARG SKAFFOLD_GO_GCFLAGS
RUN CGO_ENABLED=0 GOOS=linux go build -gcflags="${SKAFFOLD_GO_GCFLAGS}" -o /checkoutservice .

FROM scratch

WORKDIR /src
COPY --from=builder /checkoutservice /src/checkoutservice

# Definition of this variable is used by 'skaffold debug' to identify a golang binary.
# Default behavior - a failure prints a stack trace for the current goroutine.
# See https://golang.org/pkg/runtime/
ENV GOTRACEBACK=single

EXPOSE 5050
ENTRYPOINT ["/src/checkoutservice"]
