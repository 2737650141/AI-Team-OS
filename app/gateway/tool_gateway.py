"""Tool Gateway：统一鉴权/拦截/幂等/审计（M1）。"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from app.gateway.audit import AuditLog, redact
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

        # R19：幂等键查重，恢复/重放时不重复执行（JSON 规范化，兼容非字符串参数）
        key = hashlib.sha256(
            f"{tool_name}:{json.dumps(args, sort_keys=True, default=str)}".encode()
        ).hexdigest()[:16]
        if key in self._seen_keys:
            self._audit.entry(
                "tool_skipped_duplicate", task_id=self._task_id, tool=tool_name, key=key
            )
            return ToolResult(ok=False, error="duplicate call skipped", status="skipped")

        record: dict[str, Any] = {
            "id": uuid.uuid4().hex[:12],
            "tool": tool_name,
            "args": {k: redact(str(v)) for k, v in args.items()},
            "key": key,
            "role": role,
            "ts": _now(),
        }

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
                ok=False,
                error="tool blocked: approval required (M3)",
                status="blocked",
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
        record["result_summary"] = redact(str(data))[:200]
        self.tool_calls.append(record)
        self.evidence.append(
            {
                "id": uuid.uuid4().hex[:12],
                "task_id": self._task_id,
                "tool": tool_name,
                "summary": redact(str(data))[:200],
                "ts": _now(),
            }
        )
        self._audit.entry(
            "tool_ok", task_id=self._task_id, tool=tool_name, read_only=tool.read_only
        )
        return ToolResult(ok=True, data=data)
