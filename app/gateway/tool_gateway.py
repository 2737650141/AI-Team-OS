"""Tool Gateway：统一鉴权/拦截/幂等/审计（M1）。"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

from app.gateway.audit import AuditLog
from app.tools.spec import RiskLevel, ToolResult, ToolSpec


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ToolGateway:
    def __init__(self, audit: AuditLog, task_id: str) -> None:
        self._audit = audit
        self._task_id = task_id
        self._tools: dict[str, ToolSpec] = {}
        self._seen_keys: set[str] = set()
        self.tool_calls: list[dict[str, Any]] = []
        self.evidence: list[dict[str, Any]] = []
        self.approvals: list[dict[str, Any]] = []

    def register(self, tool: ToolSpec) -> None:
        self._tools[tool.name] = tool

    def invoke(self, tool_name: str, args: dict[str, Any], role: str | None = None) -> ToolResult:
        tool = self._tools.get(tool_name)
        if tool is None:
            self._audit.entry("tool_unknown", task_id=self._task_id, tool=tool_name, role=role)
            return ToolResult(ok=False, error=f"unknown tool: {tool_name}", status="error")

        # R19：幂等键查重，恢复/重放时不重复执行
        key = hashlib.sha256(f"{tool_name}:{sorted(args.items())}".encode()).hexdigest()[:16]
        if key in self._seen_keys:
            self._audit.entry(
                "tool_skipped_duplicate", task_id=self._task_id, tool=tool_name, key=key
            )
            return ToolResult(ok=False, error="duplicate call skipped", status="skipped")

        record: dict[str, Any] = {
            "id": uuid.uuid4().hex[:12],
            "tool": tool_name,
            "args": args,
            "key": key,
            "role": role,
            "ts": _now(),
        }

        # GT-10（M1）：dangerous 或 requires_approval 必须确定性拦截，
        # handler 永不执行；审批流在 M3 实现
        if tool.risk_level is RiskLevel.DANGEROUS or tool.requires_approval:
            self.approvals.append(
                {
                    "id": uuid.uuid4().hex[:12],
                    "task_id": self._task_id,
                    "tool": tool_name,
                    "args_summary": str(args)[:200],
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
                ok=False,
                error="dangerous tool blocked: approval required (M3)",
                status="blocked",
            )

        if tool.risk_level is RiskLevel.SENSITIVE and not tool.read_only:
            # M1：sensitive 暂放行并记录；审批策略 M3 落地
            self._audit.entry(
                "tool_sensitive_auto_allowed_m1",
                task_id=self._task_id,
                tool=tool_name,
            )

        try:
            data = tool.handler(**args)
        except Exception as exc:  # noqa: BLE001
            record["status"] = "error"
            self.tool_calls.append(record)
            self._audit.entry(
                "tool_error", task_id=self._task_id, tool=tool_name, error=str(exc)[:300]
            )
            return ToolResult(ok=False, error=str(exc), status="error")

        self._seen_keys.add(key)
        record["status"] = "ok"
        record["result_summary"] = str(data)[:200]
        self.tool_calls.append(record)
        self.evidence.append(
            {
                "id": uuid.uuid4().hex[:12],
                "task_id": self._task_id,
                "tool": tool_name,
                "summary": str(data)[:200],
                "ts": _now(),
            }
        )
        self._audit.entry(
            "tool_ok", task_id=self._task_id, tool=tool_name, read_only=tool.read_only
        )
        return ToolResult(ok=True, data=data)
