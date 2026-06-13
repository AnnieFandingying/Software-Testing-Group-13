"""
诊断仪表盘 HTML 渲染
====================
内嵌 HTML/CSS，不依赖外部前端框架。
"""

import json
from datetime import datetime, timezone, timedelta

# 北京时间时区
BJT = timezone(timedelta(hours=8))


def _beijing(iso_str: str) -> str:
    """将 UTC ISO 时间字符串转为北京时间显示"""
    if not iso_str:
        return ""
    try:
        # 处理 ISO 格式: 2026-06-13T14:01:31+00:00 或 2026-06-13T14:01:31.123+00:00
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(BJT).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return iso_str[:19] if len(iso_str) >= 19 else iso_str

# ============================================================================
# 基础样式
# ============================================================================

BASE_STYLE = """
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #0d1117; color: #c9d1d9; padding: 20px; line-height: 1.6;
  }
  h1 { font-size: 24px; color: #58a6ff; margin-bottom: 10px; }
  h2 { font-size: 18px; color: #f0883e; margin: 20px 0 10px; }
  table { width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 14px; }
  th { background: #161b22; padding: 10px 12px; text-align: left; border-bottom: 2px solid #30363d; }
  td { padding: 8px 12px; border-bottom: 1px solid #21262d; }
  tr:hover { background: #1c2128; }
  a { color: #58a6ff; text-decoration: none; }
  a:hover { text-decoration: underline; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 12px; }
  .badge-high { background: #238636; color: #fff; }
  .badge-mid { background: #9e6a03; color: #fff; }
  .badge-low { background: #da3633; color: #fff; }
  .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin: 15px 0; }
  .stat-card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; text-align: center; }
  .stat-value { font-size: 32px; font-weight: bold; color: #58a6ff; }
  .stat-label { font-size: 12px; color: #8b949e; margin-top: 4px; }
  .nav { margin-bottom: 20px; }
  .nav a { margin-right: 16px; padding: 6px 12px; background: #21262d; border-radius: 6px; }
  .nav a:hover { background: #30363d; text-decoration: none; }
  .meta { color: #8b949e; font-size: 13px; }
  pre { background: #161b22; padding: 15px; border-radius: 8px; overflow-x: auto; font-size: 13px; }
  .container { max-width: 1100px; margin: 0 auto; }
  .evidence-list li { margin: 6px 0; padding: 8px; background: #161b22; border-radius: 4px; border-left: 3px solid #58a6ff; }
  .footer { margin-top: 30px; text-align: center; color: #484f58; font-size: 12px; }
</style>
"""


def render_page(title: str, content: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title} — VeADK AIOps Dashboard</title>
  {BASE_STYLE}
</head>
<body>
<div class="container">
{content}
<div class="footer">VeADK AIOps Agent v1.1.0 · Auto-generated</div>
</div>
</body>
</html>"""


# ============================================================================
# 导航栏
# ============================================================================

NAV_BAR = """
<div class="nav">
  <a href="/history">诊断历史</a>
  <a href="/history?view=stats">统计面板</a>
  <a href="/history?view=cluster">集群健康</a>
  <a href="/history?view=health">健康检查</a>
  <a href="javascript:simulateAlert()" style="background:#238636;color:#fff;">⚡ 模拟告警</a>
</div>
<h1>VeADK AIOps Agent Dashboard</h1>
<div id="simulate-status" style="margin:8px 0;font-size:13px;color:#f0883e;"></div>
<script>
async function simulateAlert() {
  document.getElementById('simulate-status').innerText = '⏳ 正在触发模拟告警...';
  try {
    let r = await fetch('/simulate', {method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({alert_context:'[仪表盘模拟] frontend服务响应延迟异常，请检查'})});
    let data = await r.json();
    document.getElementById('simulate-status').innerHTML =
      '✅ 诊断完成! <a href=\"/history/'+data.record_id+'\" target=\"_blank\">查看报告 #'+data.record_id+'</a> · 耗时 '+Math.round(data.elapsed_ms)+'ms';
  } catch(e) {
    document.getElementById('simulate-status').innerText = '❌ 触发失败: '+e.message;
  }
}
</script>
"""


# ============================================================================
# 诊断历史页
# ============================================================================

def render_history(records: list[dict], stats: dict) -> str:
    if not records:
        content = NAV_BAR + "<p>暂无诊断记录。触发一次诊断后数据将显示在此处。</p>"
        return render_page("诊断历史", content)

    # 统计卡片
    stats_html = f"""
<div class="stats-grid">
  <div class="stat-card">
    <div class="stat-value">{stats.get('total', 0)}</div>
    <div class="stat-label">总诊断数</div>
  </div>
  <div class="stat-card">
    <div class="stat-value">{stats.get('avg_confidence', 0):.0%}</div>
    <div class="stat-label">平均置信度</div>
  </div>
  <div class="stat-card">
    <div class="stat-value">{stats.get('actions_count', 0)}/{stats.get('total', 1)}</div>
    <div class="stat-label">执行自愈</div>
  </div>
  <div class="stat-card">
    <div class="stat-value">{stats.get('self_heal_rate', 0):.0%}</div>
    <div class="stat-label">自愈率</div>
  </div>
</div>
"""

    # 根因分布
    categories = stats.get("categories", {})
    if categories:
        cats_html = "<div class='stats-grid' style='grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));'>"
        for cat, cnt in sorted(categories.items(), key=lambda x: -x[1]):
            cats_html += f"<div class='stat-card'><div class='stat-value' style='font-size:24px;'>{cnt}</div><div class='stat-label'>{cat}</div></div>"
        cats_html += "</div>"
    else:
        cats_html = ""

    # 记录表格
    rows = ""
    for r in records:
        rid = r.get("id", "?")
        ts = _beijing(r.get("timestamp", ""))
        summary = (r.get("alert_summary") or "")[:60]
        category = r.get("root_cause_category") or "未知"
        confidence = r.get("confidence") or 0

        if confidence >= 0.8:
            badge = "badge-high"
        elif confidence >= 0.5:
            badge = "badge-mid"
        else:
            badge = "badge-low"

        # 是否有操作
        actions = r.get("actions_taken") or "[]"
        has_action = "🔧" if actions and actions != "[]" else "🔍"

        rows += f"""
<tr>
  <td><a href="/history/{rid}">#{rid}</a> {has_action}</td>
  <td><span class="meta">{ts}</span></td>
  <td>{summary}</td>
  <td><span class="badge {badge}">{confidence:.0%}</span></td>
  <td>{category}</td>
</tr>"""

    table = f"""
<table>
<thead>
  <tr><th>ID</th><th>时间</th><th>摘要</th><th>置信度</th><th>根因分类</th></tr>
</thead>
<tbody>{rows}</tbody>
</table>
"""

    content = NAV_BAR + stats_html + cats_html + "<h2>最近诊断</h2>" + table
    return render_page("诊断历史", content)


# ============================================================================
# 统计面板页
# ============================================================================

def render_stats(stats: dict) -> str:
    """纯统计面板页面"""
    categories = stats.get("categories", {})
    cats_rows = ""
    for cat, cnt in sorted(categories.items(), key=lambda x: -x[1]):
        cats_rows += f"<tr><td>{cat}</td><td>{cnt}</td></tr>"

    content = NAV_BAR + f"""
<h2>统计面板</h2>

<div class="stats-grid">
  <div class="stat-card">
    <div class="stat-value">{stats.get('total', 0)}</div>
    <div class="stat-label">总诊断数</div>
  </div>
  <div class="stat-card">
    <div class="stat-value">{stats.get('avg_confidence', 0):.0%}</div>
    <div class="stat-label">平均置信度</div>
  </div>
  <div class="stat-card">
    <div class="stat-value">{stats.get('actions_count', 0)}/{stats.get('total', 1)}</div>
    <div class="stat-label">执行自愈</div>
  </div>
  <div class="stat-card">
    <div class="stat-value">{stats.get('self_heal_rate', 0):.0%}</div>
    <div class="stat-label">自愈成功率</div>
  </div>
</div>

<h2>根因分类分布</h2>
<table>
  <thead><tr><th>分类</th><th>次数</th></tr></thead>
  <tbody>{cats_rows if cats_rows else '<tr><td colspan="2">暂无数据</td></tr>'}</tbody>
</table>
"""
    return render_page("统计面板", content)


# ============================================================================
# 集群健康评分页
# ============================================================================

def render_cluster_health(records: list[dict]) -> str:
    """服务健康评分页面：基于最近诊断数据给每个服务打分"""
    # 从最近诊断中提取服务状态
    services = {}
    # 已知服务列表
    known_services = [
        "frontend", "checkoutservice", "cartservice", "redis-cart",
        "productcatalogservice", "currencyservice", "shippingservice",
        "paymentservice", "emailservice", "recommendationservice",
        "adservice", "discountservice", "telemetryservice", "recovery-gateway"
    ]

    for svc in known_services:
        services[svc] = {"score": 90, "status": "ok", "details": "无异常记录"}

    # 从最近诊断记录中下调异常服务分数
    for r in records[:20]:
        summary = (r.get("alert_summary") or "") + (r.get("root_cause") or "")
        category = r.get("root_cause_category") or ""
        confidence = r.get("confidence") or 0

        for svc in known_services:
            if svc in summary.lower() and confidence > 0.3:
                if category in ("依赖故障", "死锁", "连接池耗尽"):
                    services[svc]["score"] = max(10, services[svc]["score"] - 30)
                    services[svc]["status"] = "warning"
                    services[svc]["details"] = f"{category} (conf={confidence:.0%})"
                elif category in ("内存泄漏",):
                    services[svc]["score"] = max(10, services[svc]["score"] - 50)
                    services[svc]["status"] = "critical"
                    services[svc]["details"] = f"{category} (conf={confidence:.0%})"

    # 生成服务卡片
    cards = ""
    for svc in sorted(services.keys()):
        s = services[svc]
        score = s["score"]
        bar = "█" * (score // 10) + "░" * (10 - score // 10)

        if score >= 80:
            color, emoji = "#238636", "✅"
        elif score >= 50:
            color, emoji = "#9e6a03", "⚠️"
        else:
            color, emoji = "#da3633", "🔴"

        cards += f"""
<div class="stat-card" style="text-align:left;padding:12px 16px;">
  <div style="display:flex;justify-content:space-between;align-items:center;">
    <strong>{svc}</strong>
    <span style="font-size:24px;">{emoji}</span>
  </div>
  <div style="font-family:monospace;font-size:13px;margin:6px 0;color:{color};">{bar}</div>
  <div style="display:flex;justify-content:space-between;font-size:12px;color:#8b949e;">
    <span>{score}分</span>
    <span>{s['details']}</span>
  </div>
</div>"""

    avg = sum(s["score"] for s in services.values()) // len(services)
    bar_avg = "█" * (avg // 10) + "░" * (10 - avg // 10)
    color_avg = "#238636" if avg >= 80 else "#9e6a03" if avg >= 50 else "#da3633"

    content = NAV_BAR + f"""
<h2>集群健康度</h2>

<div class="stats-grid">
  <div class="stat-card">
    <div class="stat-value" style="color:{color_avg};">{avg}</div>
    <div class="stat-label">集群整体评分</div>
  </div>
  <div class="stat-card">
    <div class="stat-value" style="font-size:20px;font-family:monospace;color:{color_avg};">{bar_avg}</div>
    <div class="stat-label">健康度 (≥80=健康 50-79=注意 &lt;50=异常)</div>
  </div>
</div>

<h2>服务明细</h2>
<div class="stats-grid" style="grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));">
{cards}
</div>
"""
    return render_page("集群健康", content)


# ============================================================================
# 健康检查页
# ============================================================================

def render_health(uptime: float, diagnosis_count: int, prometheus_url: str, gateway_url: str) -> str:
    """Agent 健康检查 HTML 页面"""
    import time
    content = NAV_BAR + f"""
<h2>系统健康检查</h2>

<div class="stats-grid">
  <div class="stat-card">
    <div class="stat-value" style="color:#238636;">ONLINE</div>
    <div class="stat-label">Agent 状态</div>
  </div>
  <div class="stat-card">
    <div class="stat-value">{uptime:.0f}s</div>
    <div class="stat-label">运行时间</div>
  </div>
  <div class="stat-card">
    <div class="stat-value">{diagnosis_count}</div>
    <div class="stat-label">累计诊断</div>
  </div>
  <div class="stat-card">
    <div class="stat-value">v1.1.0</div>
    <div class="stat-label">版本号</div>
  </div>
</div>

<h2>外部服务连接</h2>
<table>
  <tr><td width="150">Prometheus</td><td><code>{prometheus_url}</code></td></tr>
  <tr><td>Recovery Gateway</td><td><code>{gateway_url}</code></td></tr>
  <tr><td>LLM 模型</td><td>deepseek-v4-pro</td></tr>
</table>
"""
    return render_page("健康检查", content)


# ============================================================================
# 详情页
# ============================================================================

def render_detail(record: dict) -> str:
    if not record:
        content = NAV_BAR + "<p>记录不存在。</p>"
        return render_page("详情", content)

    rid = record.get("id", "?")
    ts = _beijing(record.get("timestamp", ""))
    alert_summary = record.get("alert_summary", "")
    root_cause = record.get("root_cause", "")
    category = record.get("root_cause_category", "未知")
    confidence = record.get("confidence", 0)

    # 解析 JSON 字段
    try:
        actions = json.loads(record.get("actions_taken", "[]"))
    except Exception:
        actions = []
    try:
        recommendations = json.loads(record.get("recommendations", "[]"))
    except Exception:
        recommendations = []

    md_path = record.get("markdown_path", "")

    actions_html = "".join(f"<li>{a}</li>" for a in actions) if actions else "<li>无操作</li>"
    recs_html = "".join(f"<li>{r}</li>" for r in recommendations) if recommendations else "<li>无</li>"

    content = f"""
<div class="nav"><a href="/history">← 返回列表</a></div>
<h1>诊断报告 #{rid}</h1>

<h2>基本信息</h2>
<table>
  <tr><td width="120">时间</td><td>{ts}</td></tr>
  <tr><td>告警摘要</td><td>{alert_summary}</td></tr>
  <tr><td>根因</td><td>{root_cause}</td></tr>
  <tr><td>分类</td><td>{category}</td></tr>
  <tr><td>置信度</td><td>{confidence:.0%}</td></tr>
</table>

<h2>执行操作</h2>
<ul class="evidence-list">{actions_html}</ul>

<h2>后续建议</h2>
<ul class="evidence-list">{recs_html}</ul>
"""
    if md_path:
        content += f'<p style="margin-top:20px;">📄 <a href="/reports/{Path(md_path).name}" target="_blank">下载 Markdown 报告</a></p>'

    return render_page(f"诊断 #{rid}", content)


# HACK: avoid top-level import
from pathlib import Path  # noqa: E402
