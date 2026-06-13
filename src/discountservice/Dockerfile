FROM docker.1ms.run/library/golang:1.23-alpine AS builder

ENV GOPROXY=https://goproxy.io,direct \
    GO111MODULE=on \
    CGO_ENABLED=0 \
    GOOS=linux

WORKDIR /src
RUN apk add --no-cache git
COPY . .
RUN go mod tidy && go mod download
ARG SKAFFOLD_GO_GCFLAGS
RUN go build -gcflags="${SKAFFOLD_GO_GCFLAGS}" -o /discountservice .

FROM docker.1ms.run/library/alpine:3.18
WORKDIR /src
COPY --from=builder /discountservice /src/discountservice
ENV GOTRACEBACK=single
EXPOSE 50051
ENTRYPOINT ["/src/discountservice"]
