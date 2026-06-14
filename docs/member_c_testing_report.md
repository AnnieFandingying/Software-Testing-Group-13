# 成员 C：Selenium 功能测试、JMeter 并发压测与 ChaosMesh 混沌测试报告

## 1. 任务目标

成员 C 负责从用户侧和系统韧性侧验证 Online Boutique 改造后的关键链路：

1. 使用 Selenium 模拟真实用户完成浏览、设置币种、加购、结账流程。
2. 验证成员 B 新增的 `discountservice` 在 UI 支持币种 `EUR/USD/JPY/GBP/TRY/CAD` 下按 618 满减规则生效。
3. 使用 JMeter 对首页、商品模块、购物车和结账模块发起并发压测。
4. 在 JMeter 持续压测期间使用 ChaosMesh 注入故障，记录 TPS、Error Rate、p95 延迟和恢复时间。

## 2. 对 AB 交接内容的核对结论

| 交接项 | PDF/仓库信息 | C 侧采用结论 |
|---|---|---|
| 镜像交付 | AB 交接给出阿里云 ACR 公共镜像：`crpi-3qhk4rm49tlwivvp.cn-hangzhou.personal.cr.aliyuncs.com/vowit/{checkoutservice,discountservice,frontend,telemetryservice}:618-v1` | 由成员 A 部署时使用；C 测试只依赖 A 暴露的 frontend/telemetry 地址 |
| 折扣阈值 | PDF 有一处写 `200减20、400减50、700减100`；仓库 `service.go` 和 `Ability.md` 为 `200减50、400减100、700减200` | 以实际代码和仓库说明为准：`200-50`、`400-100`、`700-200` |
| 遥测地址 | PDF 有一处示例为 `/v1/metrics`；K8s 清单和代码为 `POST /events`、`GET /metrics` | 压测与 Selenium 可选遥测检查均采用 `/events` 与 `/metrics` |
| 被测主链路 | `frontend -> checkoutservice -> discountservice -> telemetryservice` | Selenium 与 JMeter 均覆盖该链路 |

## 3. 交付物清单

| 交付物 | 路径 | 说明 |
|---|---|---|
| Selenium 功能测试 | `tests/functional/checkout_discount_test.py` | 自动设置 UI 币种、加购、结账并断言折扣后实付金额 |
| Selenium 依赖 | `tests/functional/requirements.txt` | `pytest`、`selenium` |
| JMeter 压测计划 | `tests/performance/online_boutique_checkout_pressure.jmx` | 并发执行首页、设置 USD/前端支持币种、商品详情、加购、购物车、结账 |
| ChaosMesh 场景 | `tests/chaosmesh/*.yaml` | CPU、网络延迟、网络丢包、Pod failure、Pod kill |
| 混沌压测编排脚本 | `tests/performance/scripts/run_chaos_load_test.sh` | JMeter 运行中自动注入/清理 ChaosMesh 实验 |
| JTL 分析脚本 | `tests/performance/scripts/analyze_jmeter_results.py` | 输出 SLA 摘要、时间序列 CSV、SVG 曲线 |
| 运行说明 | `tests/README.md` | 给组员复现实验使用 |

## 4. Selenium 功能测试设计

### 4.1 测试策略

Selenium 不直接调用后端接口，而是从浏览器侧执行完整用户流程：

1. 打开首页。
2. 通过页面右上角币种下拉框设置 `EUR/USD/JPY/GBP/TRY/CAD`。
3. 打开商品详情页，选择数量并加入购物车。
4. 读取购物车页 `Total`，作为结账前原始金额。
5. 提交页面预填好的收货地址和信用卡信息。
6. 在订单完成页读取 `Total Paid`。
7. 根据仓库实际折扣规则计算期望金额并断言：
   - 支持币种：`>=700` 减 `200`，`>=400` 减 `100`，`>=200` 减 `50`
   - 非支持币种：不打折，订单金额应等于购物车金额

### 4.2 断言规则

| 用例编号 | 币种 | 默认商品 | 关键断言 |
|---|---|---|---|
| C-SEL-001 | USD | `1YMWWN1N4O` Watch，数量 2 | `Total Paid = Cart Total - expected_discount` |
| C-SEL-002 | EUR/JPY/GBP/TRY/CAD | 同上 | 对 UI 支持币种执行同一规则断言 |
| C-SEL-003 | telemetry | 同上 | 若提供 `TELEMETRY_METRICS_URL`，检查 `boutique_discount_hits_total{rule=...}` |

### 4.3 运行方式

```bash
python3 -m venv .venv-testing
. .venv-testing/bin/activate
pip install -r tests/functional/requirements.txt

FRONTEND_URL=http://<A_IP>:<FRONTEND_PORT> \
pytest -q tests/functional/checkout_discount_test.py
```

Selenium 每次运行会生成 JSONL 交互指标：

```text
results/testing/functional/checkout_discount_results.jsonl
```

字段包括 `set_currency_ms`、`add_to_cart_ms`、`checkout_ms`、`cart_total`、`expected_discount`、`actual_total_paid`，可作为报告截图或附录数据。

## 5. JMeter 并发压测设计

### 5.1 业务流量模型

JMeter 线程组模拟一个完整用户会话：

1. `GET /`
2. `POST /setCurrency`，设置 `currency_code=USD` 或其他 UI 支持币种
3. `GET /product/${PRODUCT_ID}`
4. `POST /cart`
5. `GET /cart`
6. `POST /cart/checkout`

`POST /cart/checkout` 加了响应断言：页面必须包含 `Your order is complete!`。

### 5.2 推荐参数

| 参数 | 建议值 | 说明 |
|---|---:|---|
| `THREADS` | 10 | 当前 Tailscale/Minikube 联调环境的稳定正式采集并发 |
| `RAMP_SECONDS` | 120 | 缓慢升压，避免基线阶段被瞬时打满 |
| `DURATION_SECONDS` | 1800 | 3-5 分钟基线 + 故障段 + 3-5 分钟恢复观察 |
| `PRODUCT_ID` | `1YMWWN1N4O` | Watch，配合数量 2 可覆盖 USD 200 档 |
| `PRODUCT_QUANTITY` | 2 | 保证 USD 默认商品链路能够触发 discountservice |

### 5.3 指标定义

| 指标 | 计算方式 | 用途 |
|---|---|---|
| TPS | `bucket_samples / bucket_seconds` | 衡量吞吐能力 |
| Error Rate | `failed_samples / total_samples` | 衡量业务失败比例 |
| p95 Latency | 每个时间桶内 `elapsed` 的 95 分位 | 衡量尾延迟 |
| Recovery Time | Chaos 删除或 Agent 自愈动作完成后，指标恢复到基线 90% 的时间 | 衡量韧性 |

## 6. ChaosMesh 场景设计

| 场景编号 | YAML | 注入点 | 预期现象 |
|---|---|---|---|
| C-CHAOS-001 | `stress-frontend-cpu.yaml` | `frontend` CPU 85% | p95 上升，Prometheus CPU 告警触发，结束后恢复 |
| C-CHAOS-002 | `network-delay-checkout-to-discount.yaml` | `checkoutservice -> discountservice` 延迟 800ms | 结账 p95 明显上升，错误率应可控 |
| C-CHAOS-003 | `network-loss-telemetry-weak-dependency.yaml` | `telemetryservice` 80% 丢包 | 监控曲线可能缺口，但主交易链路应继续成功 |
| C-CHAOS-004 | `pod-failure-productcatalogservice.yaml` | `productcatalogservice` Pod 假死 2 分钟 | 商品浏览失败率上升，恢复后回落 |
| C-CHAOS-005 | `pod-kill-checkoutservice.yaml` | 删除一个 `checkoutservice` Pod | 短暂失败尖峰，Deployment 自动重建 |

## 7. 混沌压测流程

一次标准实验分三段：

1. 基线段：JMeter 先运行 `CHAOS_DELAY_SECONDS=120` 秒，不注入故障。
2. 故障段：执行 `kubectl apply -f <CHAOS_FILE>`，持续压测。
3. 恢复段：JMeter 结束后自动 `kubectl delete -f <CHAOS_FILE>`，并用分析脚本生成报告数据。

示例命令：

```bash
FRONTEND_HOST=<A_IP> \
FRONTEND_PORT=80 \
THREADS=10 \
RAMP_SECONDS=120 \
DURATION_SECONDS=1800 \
CHAOS_DELAY_SECONDS=120 \
PRODUCT_QUANTITY=2 \
CURRENCY_CODE=USD \
CHAOS_FILE=tests/chaosmesh/network-delay-checkout-to-discount.yaml \
bash tests/performance/scripts/run_chaos_load_test.sh
```

输出目录：

```text
results/testing/jmeter/<run-name>-analysis/
```

关键产物：

- `sla_summary.md`：总体 SLA 摘要和按 label 分组指标
- `sla_timeseries.csv`：按时间桶输出 TPS、Error Rate、p95
- `sla_tps_error_rate.svg`：报告可直接引用的曲线图

## 8. 验收标准

| 验收项 | 通过标准 |
|---|---|
| Selenium 功能测试 | UI 支持币种折扣金额正确；页面出现订单完成提示 |
| JMeter 基线 | `POST Checkout` 成功率 >= 99%，p95 建议 <= 1500ms |
| checkout -> discount 延迟 | 故障段 p95 上升可观测，故障结束后 TPS 和 p95 回归基线附近 |
| telemetry 丢包 | 结账成功率接近基线，证明遥测弱依赖不阻断交易 |
| Pod kill/failure | 出现短暂错误峰值并恢复，能为成员 F 的 Agent 自愈演示提供告警素材 |

## 9. 结论

成员 C 的测试资产已经把成员 B 的折扣服务、遥测服务和成员 A 的混沌平台连接为可复现实验流程。Selenium 负责证明业务正确性，JMeter 负责持续施压，ChaosMesh 负责制造可观测故障，JTL 分析器负责输出报告级曲线和 SLA 摘要。该部分可直接作为最终大作业中“系统级功能/性能自动化测试与混沌工程”章节的主体内容。
