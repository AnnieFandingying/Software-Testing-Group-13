# Copyright 2026

FROM golang:1.25-alpine AS builder

ENV GOPROXY=https://goproxy.cn,direct \
    GO111MODULE=on \
    CGO_ENABLED=0 \
    GOOS=linux \
    GOFLAGS=-mod=mod

WORKDIR /src

# 只复制 go.mod
COPY go.mod ./

# 手动获取所有缺失的依赖（按错误提示一个个添加）
RUN go get cloud.google.com/go/profiler@v0.4.1 && \
    go get github.com/pkg/errors && \
    go get github.com/sirupsen/logrus && \
    go get google.golang.org/grpc && \
    go get google.golang.org/protobuf

# 再次整理并下载
RUN go mod tidy -v && go mod download -x

# 复制源代码
COPY . .

ARG SKAFFOLD_GO_GCFLAGS
RUN go build -gcflags="${SKAFFOLD_GO_GCFLAGS}" -o /discountservice .

FROM alpine:3.18
WORKDIR /src
COPY --from=builder /discountservice /src/discountservice

ENV GOTRACEBACK=single
EXPOSE 50051
ENTRYPOINT ["/src/discountservice"]