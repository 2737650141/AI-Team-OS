"""ToolSpec：统一工具定义（002-A 第八节 + 006 十一）。

risk_level: safe | sensitive | dangerous
read_only: bool（是否可写独立表达，不由 risk_level 表示）
requires_approval: bool
roles: 允许调用该工具的角色白名单（006 十一：角色白名单检查）
args_schema: 参数 Pydantic/JSON Schema 校验（006 十一：参数 Schema 检查）
url_validator / path_validator: URL/路径安全校验回调（web_fetch / local_* 工具）
max_result_bytes: 结果大小限制（006 十一：结果大小限制）
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
    roles: tuple[str, ...] = ()  # 空 = 任意角色（006 十一）
    args_schema: dict[str, Any] | None = None  # 参数 Schema（005 9 校验器复用）
    url_validator: Callable[[str], Any] | None = None  # 抛异常即拒绝（返回忽略）
    path_validator: Callable[[str], Any] | None = None  # 抛异常即拒绝（返回忽略）
    max_result_bytes: int = 512 * 1024
    accepts_ctx: bool = False  # M3-C：handler 需接收 ctx（写工具放行/审批绑定）
    permission_risk: str | None = None  # M6-P trusted override for the unified risk matrix
    task_explicit: bool = True  # external/system effects require an explicit task goal


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
