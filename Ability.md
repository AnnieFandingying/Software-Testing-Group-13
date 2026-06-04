# 618 Discount Service And Telemetry Service

## discount-service 功能与实现

`discount-service` 是一个独立的 gRPC 微服务，职责单一：对结算金额执行 618 满减规则计算。

### 核心规则

- 满 200 减 50
- 满 400 减 100
- 满 700 减 200
- 采用最高档单次命中，不叠加

### 输入输出

输入字段：
- `original_amount`
- `currency_code`

输出字段：
- `original_amount`
- `discount_amount`
- `final_amount`
- `applied_rule`
- `description`

### 实现细节

- 服务使用 gRPC，对应定义已补充到 `protos/demo.proto`
- 仅在 `CNY` 币种下应用 618 活动
- 若收到非 `CNY` 请求，返回 `NO_DISCOUNT` 结果，由调用方优雅跳过
- 服务在折扣计算完成后打印标准结构化日志
- 服务以短超时异步方式向 `telemetry-service` 上报 `calculate_discount` 事件

### 标准日志示例

- `event=discount_calculated service=discountservice action=calculate_discount status=ok rule=FULL_400_MINUS_100 original_amount=420 discount_amount=100 final_amount=320 duration_ms=2`

## telemetry-service 功能与实现

`telemetry-service` 是一个独立的 HTTP 微服务，负责接收核心服务上报的标准事件，并以 Prometheus 文本格式暴露聚合指标。

### 核心接口

- `POST /events`
- `GET /metrics`
- `GET /healthz`

### 事件输入模型

统一事件字段包括：
- `service`
- `action`
- `status`
- `error_type`
- `duration_ms`
- `trace_id`
- `original_total`
- `discount_amount`
- `final_total`
- `discount_rule`

### Prometheus 指标

首版在内存中聚合并输出：
- `boutique_requests_total`
- `boutique_errors_total`
- `boutique_request_duration_ms_sum`
- `boutique_discount_hits_total`
- `boutique_discount_amount_total`

### 防止基数爆炸

只允许以下低基数字段进入 Prometheus Label：
- `service`
- `action`
- `status`
- `error_type`

以下高基数字段绝不进入 Label，只保留在日志或事件中：
- `trace_id`
- `user_id`
- `original_total`
- `discount_amount`
- `final_total`
- 其他请求级唯一值

### 遥测弱依赖语义

- `POST /events` 对于 JSON 合法的请求，统一返回 `HTTP 202 Accepted`
- 即使内部聚合处理出现暂时性问题，也不返回 `500`
- 这样从协议层保证“遥测是弱依赖”，避免主链路误判失败或触发无意义重试

### 优雅停机

- `telemetry-service` 首版采用内存聚合，不做持久化
- 在 K8s 环境下捕获 `SIGTERM`
- 退出前等待 2 到 3 秒，再执行 HTTP Server Shutdown
- 这样 Prometheus 在滚动更新或自愈重启时仍有机会完成最后一次抓取，减少曲线断崖

## frontend 与 checkoutservice 的改造

### frontend

- 在 `/cart/checkout` 请求入口打印统一结构化日志
- 以短超时异步 HTTP POST 向 `telemetry-service` 上报 `place_order` 事件
- 遥测上报失败不影响用户下单流程
- 结算页面展示金额时，按 618 规则对 `CNY` 总额做显示修正，保证用户看到折后金额

### checkoutservice

当前原始链路为：
- 获取购物车
- 获取商品价格并换汇
- 获取运费
- 汇总总价
- 扣款
- 发货
- 清空购物车
- 发邮件

改造后的链路为：
- 先按原有逻辑计算 `original_total`
- 若 `UserCurrency == "CNY"`，调用 `discount-service`
- 若币种不是 `CNY`，优雅跳过折扣，令 `final_total = original_total`
- 最终使用 `final_total` 调用支付服务
- 结算完成后打印标准结构化日志
- 以短超时异步 HTTP POST 向 `telemetry-service` 上报 `place_order` 事件

## 服务间 API 交互与通信逻辑

### 1. frontend -> checkoutservice

- `frontend` 在用户提交订单时调用 `checkoutservice.PlaceOrder`
- 同时打印标准日志，并异步上报遥测事件

### 2. checkoutservice -> 现有内部服务

`checkoutservice` 保留与原有微服务的交互：
- `cartservice.GetCart`
- `productcatalogservice.GetProduct`
- `currencyservice.Convert`
- `shippingservice.GetQuote`
- `paymentservice.Charge`
- `shippingservice.ShipOrder`
- `emailservice.SendOrderConfirmation`

### 3. checkoutservice -> discount-service

- 当币种为 `CNY` 时，通过 gRPC 调用 `discount-service`
- 请求内容：`original_amount`, `currency_code`
- 响应内容：`discount_amount`, `final_amount`, `applied_rule`, `description`

### 4. discount-service -> telemetry-service

- `discount-service` 在折扣计算完成后，异步以 HTTP JSON 上报 `calculate_discount` 事件
- 同时打印一行标准结构化日志

### 5. checkoutservice -> telemetry-service

- `checkoutservice` 在扣款成功或失败后，异步以 HTTP JSON 上报 `place_order` 事件
- 遥测故障不会反向阻塞支付、发货、邮件等核心交易动作

### 6. frontend -> telemetry-service

- `frontend` 在下单入口及处理结果阶段上报 `place_order` 事件
- 采用 100ms 级短超时或 Goroutine 异步发送，避免混沌测试中 telemetry 挂掉时影响主站

### 7. telemetry-service -> Prometheus

- Prometheus 抓取 `GET /metrics`
- 聚合后的指标统一展示 `frontend`、`checkoutservice`、`discountservice` 的请求量、错误量和响应时间

## 配置与服务发现规范

所有跨服务地址通过环境变量注入，不在代码中硬编码：

- `DISCOUNT_SERVICE_ADDR`
  - 本地：`localhost:50051`
  - K8s：`discountservice:50051`
- `TELEMETRY_SERVICE_URL`
  - 本地：`http://localhost:8080/events`
  - K8s：`http://telemetryservice:8080/events`

这样本地开发与集群部署可以复用同一套代码逻辑，符合 12-Factor 应用规范。

## 测试约定

为了给自动化测试保留确定性冒烟路径，折扣规则需能稳定覆盖三档阈值：
- 满 200 档
- 满 400 档
- 满 700 档

推荐优先基于现有商品组合构造稳定用例；若现有商品价格组合不足以稳定覆盖，再额外补最小测试辅助方案。

## 成果凭证

本次修改保留完整 Git Diff，可作为大作业实现凭证。
