"""Audit Log：JSONL 结构化审计日志（R09/R20：密钥与机密脱敏）。

脱敏逻辑统一由 app/core/secrets.py 提供（006 四.4）：运行时审计与打包扫描共用
同一模式集：sk-*/ghp_*/Bearer/通用 key=token=/password=/PEM/PKCS#8 私钥块。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.core.secrets import redact as redact  # 统一脱敏（006 四.4）：与打包扫描共用模式集


class AuditLog:
    """追加式 JSONL 审计日志。"""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def entry(self, event_type: str, task_id: str | None = None, **fields: object) -> dict:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event_type,
            "task_id": task_id,
            **fields,
        }
        line = redact(json.dumps(record, ensure_ascii=False, default=str))
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        return record
