"""Tool Gateway：统一鉴权/拦截/幂等/审计（M1，003-A 二支持跨进程恢复）。

记录结构统一为 ToolCallRecord 兼容字段，可整体随 TaskState 持久化；
恢复时以 initial_* 重建内存态（幂等键、调用记录、证据、审批）。
"""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from app.gateway.audit import AuditLog, redact
from app.tools.spec import RiskLevel, ToolResult, ToolSpec


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_record(
    task_id: str, tool_name: str, args: dict[str, Any], key: str, role: str | None
) -> dict[str, Any]:
    return {
        "id": uuid.uuid4().hex[:12],
        "task_id": task_id,
        "tool": tool_name,
        "args": {k: redact(str(v)) for k, v in args.items()},
        "idempotency_key": key,
        "role": role,
        "ts": _now(),
    }


class ToolGateway:
    def __init__(
        self,
        audit: AuditLog,
        task_id: str,
        initial_keys: set[str] | None = None,
        initial_calls: list[dict[str, Any]] | None = None,
        initial_evidence: list[dict[str, Any]] | None = None,
        initial_approvals: list[dict[str, Any]] | None = None,
    ) -> None:
        self._audit = audit
        self._task_id = task_id
        self._tools: dict[str, ToolSpec] = {}
        self._seen_keys: set[str] = set(initial_keys or ())
        self.tool_calls: list[dict[str, Any]] = list(initial_calls or ())
        self.evidence: list[dict[str, Any]] = list(initial_evidence or ())
        self.approvals: list[dict[str, Any]] = list(initial_approvals or ())
        # 并行 Send 共享同一 gateway：invoke 全程加锁，保证"确定性内核"调用顺序可复现（004 二）
        self._lock = threading.Lock()

    @property
    def seen_keys(self) -> set[str]:
        return self._seen_keys

    def register(self, tool: ToolSpec) -> None:
        self._tools[tool.name] = tool

    def invoke(self, tool_name: str, args: dict[str, Any], role: str | None = None) -> ToolResult:
        """唯一工具执行入口：全程持锁，保证并行 Send 下调用顺序可复现（确定性内核）。"""
        with self._lock:
            return self._invoke(tool_name, args, role)

    def snapshot(self) -> dict:
        """锁内快照：并行 exec 回写状态用（避免锁外迭代共享集合）。"""
        with self._lock:
            return {
                "tool_calls": list(self.tool_calls),
                "evidence": list(self.evidence),
                "idempotency_keys": sorted(self._seen_keys),
            }

    def _invoke(self, tool_name: str, args: dict[str, Any], role: str | None = None) -> ToolResult:
        tool = self._tools.get(tool_name)
        if tool is None:
            self._audit.entry("tool_unknown", task_id=self._task_id, tool=tool_name, role=role)
            return ToolResult(ok=False, error=f"unknown tool: {tool_name}", status="error")

        # R19：幂等键查重，恢复/重放时不重复执行（JSON 规范化，兼容非字符串参数）
        key = hashlib.sha256(
            f"{tool_name}:{json.dumps(args, sort_keys=True, default=str)}".encode()
        ).hexdigest()[:16]
        if key in self._seen_keys:
            self._audit.entry(
                "tool_skipped_duplicate", task_id=self._task_id, tool=tool_name, key=key
            )
            return ToolResult(ok=False, error="duplicate call skipped", status="skipped")

        record = _new_record(self._task_id, tool_name, args, key, role)

        # GT-10/M1：dangerous、requires_approval 或任何非只读工具必须确定性拦截，
        # handler 永不执行；审批流在 M3 实现（非只读一律拦截，防错标风险）
        if tool.risk_level is RiskLevel.DANGEROUS or tool.requires_approval or not tool.read_only:
            self._seen_keys.add(key)  # blocked 同样登记幂等键，避免重复生成 pending approval
            self.approvals.append(
                {
                    "id": uuid.uuid4().hex[:12],
                    "task_id": self._task_id,
                    "tool": tool_name,
                    "args_summary": redact(str(args))[:200],
                    "status": "pending",
                    "decided_by": None,
                    "ts": _now(),
                }
            )
            record["status"] = "blocked"
            self.tool_calls.append(record)
            self._audit.entry(
                "tool_blocked",
                task_id=self._task_id,
                tool=tool_name,
                reason="dangerous_or_requires_approval_m1",
            )
            return ToolResult(
                ok=False, error="dangerous tool blocked: approval required (M3)", status="blocked"
            )

        try:
            data = tool.handler(**args)
        except Exception as exc:  # noqa: BLE001
            record["status"] = "error"
            self.tool_calls.append(record)
            # 异常路径同样脱敏：错误消息可能携带用户可控内容（密钥/路径）
            self._audit.entry(
                "tool_error",
                task_id=self._task_id,
                tool=tool_name,
                error=redact(str(exc))[:300],
            )
            return ToolResult(ok=False, error=redact(str(exc)), status="error")

        self._seen_keys.add(key)
        record["status"] = "ok"
        record["result_summary"] = redact(str(data))[:200]
        self.tool_calls.append(record)
        evidence_id = uuid.uuid4().hex[:12]
        self.evidence.append(
            {
                "id": evidence_id,
                "task_id": self._task_id,
                "tool": tool_name,
                "summary": redact(str(data))[:200],
                "ts": _now(),
            }
        )
        self._audit.entry(
            "tool_ok", task_id=self._task_id, tool=tool_name, read_only=tool.read_only
        )
        return ToolResult(ok=True, data=data, evidence_id=evidence_id)
