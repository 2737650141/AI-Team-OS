"""Audit Log：JSONL 结构化审计日志（R09/R20：密钥与机密脱敏）。

脱敏为"尽力而为"：覆盖 sk-*/Bearer/AKIA/ghp_/api_key=/password=/PEM 整块等常见形态；
裸密钥值（无键名前缀）与不完整 PEM（有 BEGIN 无 END）是已知边界，不做全覆盖承诺。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

_SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9_-]{8,}"
    r"|Bearer\s+[A-Za-z0-9._-]{8,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|ghp_[A-Za-z0-9]{36}"
    r"|api_key[=:]\s*[\"']?[A-Za-z0-9._-]{8,}"
    r"|password[=:]\s*[\"']?[A-Za-z0-9._-]{8,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----)",
    re.DOTALL,
)


def redact(text: str) -> str:
    """把疑似密钥内容替换为 ***。"""
    return _SECRET_RE.sub("***", text)


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
