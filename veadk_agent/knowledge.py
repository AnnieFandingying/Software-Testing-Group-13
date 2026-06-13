"""
根因知识库模块
==============
每次诊断后自动提取经验存入知识库。
下次诊断时检索相似历史案例作为 LLM 参考。
实现简化版 RAG（Retrieval-Augmented Generation）。
"""

import json
import logging
import sqlite3
from pathlib import Path
from typing import Optional

logger = logging.getLogger("veadk.knowledge")

KB_PATH = Path(__file__).resolve().parent.parent / "knowledge_base.db"


class KnowledgeBase:
    """根因案例知识库"""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or KB_PATH
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS knowledge (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    diagnosis_id INTEGER,
                    service TEXT,
                    root_cause_category TEXT,
                    root_cause TEXT,
                    symptoms TEXT,
                    resolution TEXT,
                    confidence REAL,
                    timestamp TEXT
                )
            """)
            conn.commit()

    def add(
        self,
        diagnosis_id: int,
        service: str,
        category: str,
        root_cause: str,
        symptoms: str,
        resolution: str,
        confidence: float,
    ):
        """添加一条经验"""
        from datetime import datetime, timezone
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                """INSERT INTO knowledge
                   (diagnosis_id, service, root_cause_category, root_cause,
                    symptoms, resolution, confidence, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    diagnosis_id, service, category, root_cause,
                    symptoms, resolution, confidence,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()
        logger.info("知识库已更新: service=%s category=%s", service, category)

    def search(self, service: Optional[str] = None, category: Optional[str] = None, limit: int = 3) -> list[dict]:
        """检索相似历史案例"""
        conditions = []
        params = []

        if service:
            conditions.append("service LIKE ?")
            params.append(f"%{service}%")
        if category:
            conditions.append("root_cause_category = ?")
            params.append(category)

        where = "WHERE " + " OR ".join(conditions) if conditions else ""
        sql = f"SELECT * FROM knowledge {where} ORDER BY id DESC LIMIT ?"
        params.append(limit)

        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    def get_latest(self, limit: int = 5) -> list[dict]:
        """获取最近的经验"""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM knowledge ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def stats(self) -> dict:
        """知识库统计"""
        with sqlite3.connect(str(self.db_path)) as conn:
            total = conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
            if total == 0:
                return {"total": 0, "categories": {}}
            cats = conn.execute(
                "SELECT root_cause_category, COUNT(*) FROM knowledge GROUP BY root_cause_category ORDER BY COUNT(*) DESC"
            ).fetchall()
            return {"total": total, "categories": {c[0]: c[1] for c in cats}}


# 全局单例
_kb: Optional[KnowledgeBase] = None


def get_kb() -> KnowledgeBase:
    global _kb
    if _kb is None:
        _kb = KnowledgeBase()
    return _kb


def extract_and_store(diagnosis_id: int, alert_context: str, report_json: dict):
    """
    从诊断结果中提取经验并存入知识库。
    在每次诊断完成后自动调用。
    """
    if not report_json:
        return

    # 尝试从告警中提取服务名
    service = "unknown"
    for svc in ["frontend", "checkoutservice", "cartservice", "redis-cart",
                "discountservice", "telemetryservice", "recovery-gateway",
                "paymentservice", "shippingservice", "adservice", "currencyservice",
                "emailservice", "recommendationservice", "productcatalogservice"]:
        if svc in alert_context.lower() or svc in str(report_json).lower():
            service = svc
            break

    category = report_json.get("root_cause_category", "未知")
    root_cause = report_json.get("root_cause", "")[:500]
    confidence = report_json.get("confidence", 0)

    # 合成症状描述
    symptoms = alert_context[:300]

    # 合成解决措施
    actions = report_json.get("actions_taken", [])
    recommendations = report_json.get("recommendations", [])
    resolution = "; ".join(actions + recommendations)[:500] or "未执行操作"

    if confidence > 0.3:  # 只存储有意义的诊断
        get_kb().add(diagnosis_id, service, category, root_cause, symptoms, resolution, confidence)


def get_knowledge_context(alert_context: str) -> str:
    """
    检索相关知识库案例，生成上下文注入到 System Prompt。
    返回空字符串或格式化的案例参考文本。
    """
    kb = get_kb()
    if kb.stats()["total"] == 0:
        return ""

    # 尝试从告警中提取服务名和关键词
    candidates = kb.get_latest(limit=5)
    if not candidates:
        return ""

    related = []
    for c in candidates:
        svc = c.get("service", "")
        if svc in alert_context.lower() or svc == "unknown":
            related.append(c)

    if not related:
        related = candidates[:2]  # 没有精确匹配就用最近的

    lines = ["\n## 历史相似案例（供参考，但不能替代当前诊断）\n"]
    for i, c in enumerate(related, 1):
        lines.append(
            f"{i}. **[案例 #{c.get('diagnosis_id', '?')}]** "
            f"服务: `{c.get('service')}` | "
            f"分类: `{c.get('root_cause_category')}` | "
            f"根因: {c.get('root_cause', 'N/A')[:120]} | "
            f"解决: {c.get('resolution', 'N/A')[:120]}"
        )

    return "\n".join(lines)


def bulk_extract_and_store(alert_context: str, report_json: dict, diagnosis_id: int):
    """聚合告警场景下的知识提取"""
    # 从复合告警中提取多个服务
    for svc in ["frontend", "checkoutservice", "cartservice", "redis-cart",
                "discountservice", "telemetryservice", "recovery-gateway",
                "paymentservice", "shippingservice", "adservice"]:
        if svc in alert_context.lower():
            extract_and_store(diagnosis_id, alert_context, report_json)
            break  # 只存一次，但尽量匹配到具体服务
    else:
        extract_and_store(diagnosis_id, alert_context, report_json)
