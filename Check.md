# 编译期自检清单与联调测试清单

## 1. 环境前置检查

- 确认已安装 `go 1.23+`
- 确认已安装 `protoc`
- 确认已安装 `protoc-gen-go`
- 确认已安装 `protoc-gen-go-grpc`
- 确认已安装 `docker`
- 确认已安装 `kubectl`
- 确认已安装 `skaffold`

建议执行：

```bash
go version
protoc --version
protoc-gen-go --version
protoc-gen-go-grpc --version
docker --version
kubectl version --client
skaffold version
```

## 2. Proto 与代码生成检查

### 目标

确认 `discount-service` 的 gRPC 协议定义与本地生成代码一致。

### 检查项

- `protos/demo.proto` 中存在 `DiscountService`
- `protos/demo.proto` 中存在：
  - `GetDiscountRequest`
  - `GetDiscountResponse`
- 各 Go 服务若依赖该 proto，需重新生成代码

### 建议执行

```bash
grep -n "DiscountService\|GetDiscountRequest\|GetDiscountResponse" protos/demo.proto
```

如本地具备工具链，进入相关目录重新生成：

```bash
cd src/checkoutservice && ./genproto.sh
cd ../frontend && ./genproto.sh
```

如果后续把 `discountservice` 也改为使用统一 `demo.proto` 自动生成，同样需要补一个对应的 `genproto.sh`。

## 3. Go 编译期自检

### checkoutservice

```bash
cd /root/autodl-tmp/Online-Boutique/src/checkoutservice
go test ./...
go build ./...
```

重点确认：

- `main.go` 能成功编译
- `discount.go` 无未使用导入、无类型冲突
- `genproto/discount.pb.go` 与现有 `genproto` 不发生包冲突

### frontend

```bash
cd /root/autodl-tmp/Online-Boutique/src/frontend
go test ./...
go build ./...
```

重点确认：

- `telemetry.go` 能成功编译
- `pricing.go` 与现有 `money` 包配合正常
- `handlers.go` 中 `placeOrderHandler` 和 `assistantHandler` 无回归

### discountservice

```bash
cd /root/autodl-tmp/Online-Boutique/src/discountservice
go test ./...
go build ./...
```

重点确认：

- `service_test.go` 通过
- `main.go` 与 `service.go` 无接口不匹配
- `RegisterDiscountServiceServer` 与服务实现匹配

### telemetryservice

```bash
cd /root/autodl-tmp/Online-Boutique/src/telemetryservice
go test ./...
go build ./...
```

重点确认：

- `main_test.go` 通过
- `/events` 返回 `202`
- `/metrics` 输出 Prometheus 文本

## 4. 静态仓库结构检查

### 检查项

- `src/discountservice/` 存在
- `src/telemetryservice/` 存在
- `kubernetes-manifests/discountservice.yaml` 存在
- `kubernetes-manifests/telemetryservice.yaml` 存在
- `helm-chart/templates/discountservice.yaml` 存在
- `helm-chart/templates/telemetryservice.yaml` 存在
- `Ability.md` 已更新

### 建议执行

```bash
find src/discountservice src/telemetryservice kubernetes-manifests helm-chart/templates -maxdepth 2 -type f | sort
```

## 5. 配置注入检查

### checkoutservice

必须存在：

- `DISCOUNT_SERVICE_ADDR`
- `TELEMETRY_SERVICE_URL`

### frontend

必须存在：

- `TELEMETRY_SERVICE_URL`

### discountservice

必须存在：

- `TELEMETRY_SERVICE_URL`

### 建议执行

```bash
grep -RIn "DISCOUNT_SERVICE_ADDR\|TELEMETRY_SERVICE_URL" \
  kubernetes-manifests \
  helm-chart/templates \
  src/checkoutservice \
  src/frontend \
  src/discountservice
```

## 6. 本地运行联调清单

### 目标

确认主交易链路、折扣链路、遥测链路可同时工作。

### 建议地址

- `DISCOUNT_SERVICE_ADDR=localhost:50051`
- `TELEMETRY_SERVICE_URL=http://localhost:8080/events`

### 本地启动顺序建议

1. 先启动 `telemetryservice`
2. 再启动 `discountservice`
3. 再启动其余原有微服务
4. 最后启动 `frontend`

### 建议验证

- 访问前台页面正常
- 提交订单时不报 500
- `checkoutservice` 能调用 `discountservice`
- `telemetryservice` 能收到事件
- `telemetryservice` 的 `/metrics` 可访问

## 7. 618 满减业务断言

### 核心断言

- 满 200 减 50
- 满 400 减 100
- 满 700 减 200
- 只命中最高档，不叠加
- 非 `CNY` 币种不调用折扣或优雅跳过

### 测试样例

#### 样例 A：200 档

- 原价：`CNY 210`
- 预期折扣：`50`
- 预期实付：`160`

#### 样例 B：400 档

- 原价：`CNY 420`
- 预期折扣：`100`
- 预期实付：`320`

#### 样例 C：700 档

- 原价：`CNY 720`
- 预期折扣：`200`
- 预期实付：`520`

#### 样例 D：非 CNY

- 原价：`USD 720`
- 预期折扣：`0`
- 预期实付：`720`

## 8. 前端页面与金额展示检查

### 检查项

- 下单成功页显示的 `total_paid` 与折后金额一致
- `CNY` 时页面展示折后总额
- 非 `CNY` 时页面展示原总额
- 不出现“支付按折后价扣款，但页面仍显示原价”的不一致

## 9. 遥测弱依赖容灾检查

### 目标

确认 `telemetry-service` 挂掉时，主交易链路仍然成功。

### 验证方法

1. 正常启动全链路，下单一次，确认成功
2. 手动停掉 `telemetryservice`
3. 再次下单
4. 预期：
   - `frontend` 仍可提交订单
   - `checkoutservice` 仍可完成支付与发货
   - 日志中最多出现 Warning
   - 不应因遥测失败导致主链路 500

## 10. telemetry-service 行为检查

### `/events`

检查项：

- 合法 JSON 返回 `202 Accepted`
- 非法 JSON 返回 `400`
- 即使内部聚合失败，也不应轻易返回 `500`

### `/metrics`

检查项：

- 响应码为 `200`
- `Content-Type` 为 Prometheus 文本
- 至少存在：
  - `boutique_requests_total`
  - `boutique_errors_total`
  - `boutique_request_duration_ms_sum`
  - `boutique_discount_hits_total`
  - `boutique_discount_amount_total`

### 建议执行

```bash
curl -i http://localhost:8080/events \
  -H 'Content-Type: application/json' \
  -d '{"service":"frontend","action":"place_order","status":"ok","error_type":"none","duration_ms":12}'

curl -s http://localhost:8080/metrics
```

## 11. Prometheus Label 基数检查

### 允许进入 Label 的字段

- `service`
- `action`
- `status`
- `error_type`

### 不允许进入 Label 的字段

- `trace_id`
- `user_id`
- `original_total`
- `discount_amount`
- `final_total`

### 验证目标

- `/metrics` 输出中不应出现 `trace_id`
- `/metrics` 输出中不应出现连续金额值作为 label key/value

### 建议执行

```bash
curl -s http://localhost:8080/metrics | grep -E "trace_id|original_total|final_total|discount_amount"
```

预期：无输出。

## 12. 优雅停机检查

### 目标

确认 `telemetryservice` 捕获 `SIGTERM` 后不会立刻硬退出。

### 检查方法

1. 启动 `telemetryservice`
2. 发送若干事件
3. 发送 `SIGTERM`
4. 观察进程是否延迟约 2 到 3 秒再退出

### 建议执行

```bash
pkill -TERM -f telemetryservice
```

如需更精确，可在日志中加入退出时间戳比对。

## 13. Kubernetes 部署检查

### 建议执行

```bash
cd /root/autodl-tmp/Online-Boutique
skaffold dev
```

或：

```bash
kubectl apply -k kubernetes-manifests
kubectl get pods
kubectl get svc
```

### 核心检查项

- `discountservice` Pod 正常 Running
- `telemetryservice` Pod 正常 Running
- `checkoutservice` 注入了新环境变量
- `frontend` 注入了 `TELEMETRY_SERVICE_URL`
- `discountservice` Service 端口为 `50051`
- `telemetryservice` Service 端口为 `8080`

## 14. Git Diff 成果凭证检查

### 建议执行

```bash
git status --short
git diff --stat
git diff -- Ability.md
git diff -- protos/demo.proto
git diff -- src/checkoutservice/main.go
git diff -- src/frontend/handlers.go
```

### 目标

- 能清晰证明新增了两个微服务
- 能清晰证明修改了 `checkoutservice`
- 能清晰证明补充了 K8s 与 Helm 清单
- 能清晰证明更新了设计说明文档

## 15. 建议最终验收顺序

1. 先做工具链检查
2. 再做 `go test` / `go build`
3. 再做 proto 生成检查
4. 再做本地联调
5. 再做遥测弱依赖故障注入
6. 最后做 K8s / skaffold 部署验证
7. 保存 Git Diff 作为成果证明

