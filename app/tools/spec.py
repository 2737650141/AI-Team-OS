"""ToolSpec：统一工具定义（002-A 第八节）。

risk_level: safe | sensitive | dangerous
read_only: bool（是否可写独立表达，不由 risk_level 表示）
requires_approval: bool
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable


class RiskLevel(str, Enum):
    SAFE = "safe"
    SENSITIVE = "sensitive"
    DANGEROUS = "dangerous"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    risk_level: RiskLevel
    read_only: bool
    handler: Callable[..., Any]
    requires_approval: bool = False


@dataclass
class ToolResult:
    ok: bool
    data: Any = None
    error: str | None = None
    status: str = "ok"  # ok | blocked | error | skipped | cached_success_result
    evidence_id: str | None = None  # 成功调用产生的 evidence 记录 id（gateway 生成）
    cached_from: str | None = None  # 缓存命中：原 evidence 记录 id
    original_ts: str | None = None  # 缓存命中：原始执行时间
    content_hash: str | None = None  # 缓存命中：内容哈希
