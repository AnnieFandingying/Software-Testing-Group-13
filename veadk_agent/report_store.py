"""
诊断历史存储 + Markdown 报告生成
================================
1. DiagnosisStore: SQLite 持久化诊断记录
2. ReportGenerator: 生成结构化 Markdown 报告文件
"""

import json
import logging
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("veadk.report")

# 报告输出目录
REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"
DB_PATH = Path(__file__).resolve().parent.parent / "diagnosis_history.db"


# ============================================================================
# SQLite 诊断历史存储
# ============================================================================

class DiagnosisStore:
    """SQLite 诊断记录持久化"""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_PATH
        self._init_db()

    def _init_db(self):
        """创建表（如果不存在）"""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS diagnoses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    alert_summary TEXT,
                    root_cause TEXT,
                    root_cause_category TEXT,
                    confidence REAL,
                    actions_taken TEXT,
                    recommendations TEXT,
                    report_json TEXT,
                    markdown_path TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                )
            """)
            conn.commit()

    def save(
        self,
        alert_context: str,
        report_text: str,
        report_json: Optional[dict] = None,
        actions: Optional[list] = None,
        markdown_path: str = "",
    ) -> int:
        """
        存入一条诊断记录，返回自增 ID。
        自动从 report_json 中提取结构化字段。
        """
        if report_json is None:
            report_json = {}

        timestamp = report_json.get("alert_time", datetime.now(timezone.utc).isoformat())
        alert_summary = report_json.get("alert_summary", alert_context[:200])
        root_cause = report_json.get("root_cause", "")
        root_cause_category = report_json.get("root_cause_category", "未知")
        confidence = report_json.get("confidence", 0.0)
        actions_taken = json.dumps(report_json.get("actions_taken", actions or []), ensure_ascii=False)
        recommendations = json.dumps(report_json.get("recommendations", []), ensure_ascii=False)

        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.execute(
                """INSERT INTO diagnoses
                   (timestamp, alert_summary, root_cause, root_cause_category,
                    confidence, actions_taken, recommendations, report_json, markdown_path)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    timestamp,
                    alert_summary,
                    root_cause,
                    root_cause_category,
                    confidence,
                    actions_taken,
                    recommendations,
                    json.dumps(report_json, ensure_ascii=False),
                    markdown_path,
                ),
            )
            conn.commit()
            row_id = cursor.lastrowid
            logger.info("诊断记录已保存: id=%d category=%s confidence=%.2f", row_id, root_cause_category, confidence)
            return row_id

    def get_all(self, limit: int = 20, offset: int = 0) -> list[dict]:
        """分页获取诊断列表"""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM diagnoses ORDER BY id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_by_id(self, record_id: int) -> Optional[dict]:
        """获取单条诊断详情"""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM diagnoses WHERE id = ?", (record_id,)
            ).fetchone()
            return dict(row) if row else None

    def stats(self) -> dict:
        """聚合统计"""
        with sqlite3.connect(str(self.db_path)) as conn:
            total = conn.execute("SELECT COUNT(*) FROM diagnoses").fetchone()[0]

            if total == 0:
                return {
                    "total": 0, "avg_confidence": 0,
                    "categories": {}, "actions_count": 0,
                    "self_heal_rate": 0,
                }

            avg_conf = conn.execute(
                "SELECT AVG(confidence) FROM diagnoses"
            ).fetchone()[0] or 0

            # 根因分类分布
            cats = conn.execute(
                "SELECT root_cause_category, COUNT(*) as cnt FROM diagnoses GROUP BY root_cause_category ORDER BY cnt DESC"
            ).fetchall()

            # 有实际操作（非空 actions）的记录数
            actions_count = conn.execute(
                "SELECT COUNT(*) FROM diagnoses WHERE actions_taken != '[]' AND actions_taken != ''"
            ).fetchone()[0]

            return {
                "total": total,
                "avg_confidence": round(avg_conf, 3),
                "categories": {c[0]: c[1] for c in cats},
                "actions_count": actions_count,
                "self_heal_rate": round(actions_count / total, 3) if total > 0 else 0,
            }

    def count(self) -> int:
        """总记录数"""
        with sqlite3.connect(str(self.db_path)) as conn:
            return conn.execute("SELECT COUNT(*) FROM diagnoses").fetchone()[0]


# 全局单例
_store: Optional[DiagnosisStore] = None


def get_store() -> DiagnosisStore:
    global _store
    if _store is None:
        _store = DiagnosisStore()
    return _store


# ============================================================================
# Markdown 报告生成器
# ============================================================================

class ReportGenerator:
    """将诊断结果生成结构化 Markdown 报告"""

    @staticmethod
    def generate(record: dict) -> str:
        """
        根据诊断记录字典生成 Markdown 报告文本。
        """
        rid = record.get("id", "N/A")
        timestamp = record.get("timestamp", "")
        alert_summary = record.get("alert_summary", "")
        root_cause = record.get("root_cause", "")
        root_cause_category = record.get("root_cause_category", "未知")
        confidence = record.get("confidence", 0.0)

        # 解析 JSON 字段
        try:
            actions = json.loads(record.get("actions_taken", "[]"))
        except (json.JSONDecodeError, TypeError):
            actions = []
        try:
            recommendations = json.loads(record.get("recommendations", "[]"))
        except (json.JSONDecodeError, TypeError):
            recommendations = []
        try:
            report_json = json.loads(record.get("report_json", "{}"))
        except (json.JSONDecodeError, TypeError):
            report_json = {}

        evidence = report_json.get("supporting_evidence", [])

        # 置信度级别
        if confidence >= 0.8:
            conf_level = "🟢 高"
        elif confidence >= 0.5:
            conf_level = "🟡 中"
        else:
            conf_level = "🔴 低"

        lines = [
            f"# AIOps Agent 诊断报告 #{rid}",
            "",
            f"**生成时间**: {timestamp}",
            f"**诊断耗时**: {record.get('created_at', 'N/A')}",
            "",
            "---",
            "",
            "## 告警摘要",
            "",
            alert_summary,
            "",
            "## 根因分析",
            "",
            f"| 项目 | 内容 |",
            f"|------|------|",
            f"| **根因** | {root_cause} |",
            f"| **分类** | `{root_cause_category}` |",
            f"| **置信度** | {confidence:.0%} {conf_level} |",
            "",
        ]

        if evidence:
            lines.append("## 支持证据")
            lines.append("")
            for i, ev in enumerate(evidence, 1):
                lines.append(f"{i}. {ev}")
            lines.append("")

        if actions:
            lines.append("## 执行操作")
            lines.append("")
            for a in actions:
                lines.append(f"- ✅ {a}")
            lines.append("")

        if recommendations:
            lines.append("## 后续建议")
            lines.append("")
            for r in recommendations:
                lines.append(f"- 📋 {r}")
            lines.append("")

        lines.extend([
            "---",
            "",
            f"*报告由 VeADK AIOps Agent v1.1.0 自动生成*",
        ])

        return "\n".join(lines)

    @staticmethod
    def save_to_file(markdown_text: str, record_id: int) -> str:
        """
        将 Markdown 文本保存到 reports/ 目录。
        返回文件路径。
        """
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)

        date_prefix = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        filename = f"{date_prefix}-diagnosis-{record_id:04d}.md"
        filepath = REPORTS_DIR / filename

        filepath.write_text(markdown_text, encoding="utf-8")
        logger.info("Markdown 报告已保存: %s", filepath)
        return str(filepath)


# ============================================================================
# 便捷函数
# ============================================================================

def save_diagnosis(alert_context: str, report_text: str, report_json: Optional[dict] = None) -> int:
    """保存诊断 → SQLite + Markdown 文件，返回记录 ID"""
    store = get_store()

    # 尝试从 report_text 中提取 JSON
    if report_json is None:
        report_json = _extract_json(report_text)

    # 先存数据库获取 ID
    record_id = store.save(alert_context, report_text, report_json)

    # 生成 Markdown 报告
    record = store.get_by_id(record_id)
    if record:
        md_text = ReportGenerator.generate(record)
        md_path = ReportGenerator.save_to_file(md_text, record_id)

        # 回写 markdown 路径
        with sqlite3.connect(str(store.db_path)) as conn:
            conn.execute(
                "UPDATE diagnoses SET markdown_path = ? WHERE id = ?",
                (md_path, record_id),
            )
            conn.commit()

    return record_id


def _extract_json(text: str) -> dict:
    """从 LLM 输出中提取 JSON 块"""
    try:
        # 尝试直接解析
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 尝试提取 ```json ... ``` 代码块
    import re
    match = re.search(r'```json\s*\n(.*?)\n```', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # 尝试提取 { ... } 块
    match = re.search(r'\{[^{}]*"alert_time"[^{}]*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return {}
