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

from app.core.approval import ApprovalError, ApprovalService
from app.core.evidence import EvidenceQuotaExceeded, EvidenceWriter
from app.core.secrets import redact
from app.gateway.audit import AuditLog
from app.gateway.tool_policy import (
    ToolExecutionContext,
    ToolPolicy,
    ToolQuota,
)
from app.tools.spec import RiskLevel, ToolResult, ToolSpec


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _source_type_of(tool_name: str) -> str:
    """工具名 → Evidence source_type（006 五）。"""
    for prefix in ("github", "web", "local", "mcp", "fixture"):
        if tool_name.startswith(prefix):
            return prefix
    return "tool"


def _new_record(
    task_id: str,
    tool_name: str,
    args: dict[str, Any],
    key: str,
    role: str | None,
    subtask_id: str | None = None,
) -> dict[str, Any]:
    return {
        "id": uuid.uuid4().hex[:12],
        "task_id": task_id,
        "tool": tool_name,
        "args": {k: redact(str(v)) for k, v in args.items()},
        "idempotency_key": key,
        "role": role,
        "subtask_id": subtask_id,
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
        policy: ToolPolicy | None = None,
        evidence_writer: EvidenceWriter | None = None,
        approval_service: ApprovalService | None = None,
    ) -> None:
        self._audit = audit
        self._task_id = task_id
        self._tools: dict[str, ToolSpec] = {}
        self._seen_keys: set[str] = set(initial_keys or ())
        self.tool_calls: list[dict[str, Any]] = list(initial_calls or ())
        self.evidence: list[dict[str, Any]] = list(initial_evidence or ())
        self.approvals: list[dict[str, Any]] = list(initial_approvals or ())
        # 幂等键 → 成功结果缓存（004 4.x）：命中时复用完整结构化结果，handler 不重复执行
        self._result_cache: dict[str, dict[str, Any]] = {}
        # 006 十一：策略 / 配额 / Evidence 固化器；007 5.4：审批服务（写工具放行）
        self.policy = policy or ToolPolicy()
        self._quota = ToolQuota(self.policy)
        self.evidence_writer = evidence_writer
        self._approval_service = approval_service
        # 并行 Send 共享同一 gateway：invoke 全程加锁，保证"确定性内核"调用顺序可复现（004 二）
        self._lock = threading.Lock()

    @property
    def seen_keys(self) -> set[str]:
        return self._seen_keys

    def register(self, tool: ToolSpec) -> None:
        self._tools[tool.name] = tool

    def available_tools(self) -> list[str]:
        """可用工具名（006 十二：研究者工具循环的允许集合）。"""
        return sorted(self._tools.keys())

    def invoke(
        self,
        tool_name: str,
        args: dict[str, Any],
        role: str | None = None,
        ctx: ToolExecutionContext | None = None,
    ) -> ToolResult:
        """唯一工具执行入口：全程持锁，保证并行 Send 下调用顺序可复现（确定性内核）。"""
        with self._lock:
            return self._invoke(tool_name, args, role, ctx)

    def snapshot(self) -> dict:
        """锁内快照：并行 exec 回写状态用（避免锁外迭代共享集合）。"""
        with self._lock:
            return {
                "tool_calls": list(self.tool_calls),
                "evidence": list(self.evidence),
                "idempotency_keys": sorted(self._seen_keys),
            }

    def _invoke(
        self,
        tool_name: str,
        args: dict[str, Any],
        role: str | None = None,
        ctx: ToolExecutionContext | None = None,
    ) -> ToolResult:
        tool = self._tools.get(tool_name)
        if tool is None:
            self._audit.entry("tool_unknown", task_id=self._task_id, tool=tool_name, role=role)
            return ToolResult(ok=False, error=f"unknown tool: {tool_name}", status="error")

        # 006 十一 执行流程：角色白名单 → 只读/风险 → 参数 Schema → URL/路径安全 → 配额
        effective_role = role or (ctx.role if ctx else None) or ""
        if tool.roles and effective_role not in tool.roles:
            self._audit.entry(
                "tool_role_denied", task_id=self._task_id, tool=tool_name, role=effective_role
            )
            return ToolResult(
                ok=False,
                error=f"tool {tool_name} not allowed for role {effective_role}",
                status="blocked",
            )
        if tool.args_schema:
            try:
                from app.core.output_governance import build_validator

                build_validator(tool.args_schema).model_validate(args)
            except Exception as exc:  # noqa: BLE001
                self._audit.entry(
                    "tool_args_rejected",
                    task_id=self._task_id,
                    tool=tool_name,
                    error=redact(str(exc))[:200],
                )
                return ToolResult(
                    ok=False, error="tool arguments rejected by schema", status="blocked"
                )
        if tool.url_validator is not None and "url" in args:
            try:
                tool.url_validator(str(args["url"]))
            except Exception as exc:  # noqa: BLE001
                self._audit.entry(
                    "tool_url_rejected",
                    task_id=self._task_id,
                    tool=tool_name,
                    error=redact(str(exc))[:200],
                )
                return ToolResult(ok=False, error="url rejected by policy", status="blocked")
        if tool.path_validator is not None:
            for key in ("path", "dir"):
                if key in args:
                    try:
                        tool.path_validator(str(args[key]))
                    except Exception as exc:  # noqa: BLE001
                        self._audit.entry(
                            "tool_path_rejected",
                            task_id=self._task_id,
                            tool=tool_name,
                            error=redact(str(exc))[:200],
                        )
                        return ToolResult(
                            ok=False, error="path rejected by policy", status="blocked"
                        )
        try:
            self._quota.check_and_reserve(ctx)
            self._quota.check_evidence(self.evidence_writer)
        except ValueError as exc:
            self._audit.entry(
                "tool_quota_exceeded",
                task_id=self._task_id,
                tool=tool_name,
                error=redact(str(exc))[:200],
            )
            return ToolResult(ok=False, error=f"quota exceeded: {exc}", status="blocked")

        # R19：幂等键查重，恢复/重放时不重复执行（JSON 规范化，兼容非字符串参数）
        key = hashlib.sha256(
            f"{tool_name}:{json.dumps(args, sort_keys=True, default=str)}".encode()
        ).hexdigest()[:16]
        if key in self._seen_keys:
            hit = self._result_cache.get(key)
            if hit is None:
                # 跨进程恢复后缓存为空：从 evidence 记录恢复退化缓存（脱敏摘要 + 证据引用）
                for e in reversed(self.evidence):
                    if e.get("idempotency_key") == key:
                        hit = {
                            "data": e.get("summary", ""),
                            "evidence_id": e["id"],
                            "ts": e.get("ts", ""),
                            "hash": e.get("content_hash", ""),
                        }
                        self._result_cache[key] = hit
                        break
            if hit is not None:
                # 004 4.1：cached_success_result —— 复用已有成功结果，不重复执行副作用
                record = _new_record(
                    self._task_id,
                    tool_name,
                    args,
                    key,
                    role,
                    ctx.subtask_id if ctx else None,
                )
                record["status"] = "cached_success_result"
                record["cached_from"] = hit["evidence_id"]
                record["content_hash"] = hit.get("hash", "")
                self.tool_calls.append(record)
                self._audit.entry(
                    "tool_cached_success", task_id=self._task_id, tool=tool_name, key=key
                )
                return ToolResult(
                    ok=True,
                    data=hit["data"],
                    status="cached_success_result",
                    evidence_id=hit["evidence_id"],
                    cached_from=hit["evidence_id"],
                    original_ts=hit.get("ts"),
                    content_hash=hit.get("hash"),
                )
            self._audit.entry(
                "tool_skipped_duplicate", task_id=self._task_id, tool=tool_name, key=key
            )
            return ToolResult(
                ok=False, error="duplicate call skipped (no cached result)", status="skipped"
            )

        record = _new_record(
            self._task_id, tool_name, args, key, role, ctx.subtask_id if ctx else None
        )

        # GT-10/M1：dangerous、requires_approval 或任何非只读工具必须确定性拦截，
        # handler 永不执行；M3-C 审批流：ctx.approval_id + 已批准才放行（007 5.4）
        approved_pass = False
        if tool.risk_level is RiskLevel.DANGEROUS or tool.requires_approval or not tool.read_only:
            if ctx and ctx.approval_id and self._approval_service is not None:
                request = self._approval_service.get(ctx.approval_id)
                if request is not None:
                    try:
                        # 放行验证（5.3/5.4）：操作哈希绑定 + 实际参数哈希绑定（GT-W04）
                        self._approval_service.verify_execution(
                            request,
                            parameter_hash=ApprovalService.parameter_hash_of(args),
                            target_hash="",
                            operation_hash=request.operation_hash,
                        )
                        approved_pass = True  # 放行：继续执行 handler
                    except ApprovalError as exc:
                        # M3-C：审批无效不登记幂等键——批准后可重试（GT-W01/W03）
                        self.tool_calls.append(record)
                        self._audit.entry(
                            "tool_blocked",
                            task_id=self._task_id,
                            tool=tool_name,
                            reason=f"approval_not_valid: {str(exc)[:100]}",
                        )
                        return ToolResult(
                            ok=False, error=f"approval invalid: {exc}", status="blocked"
                        )
                else:
                    self.tool_calls.append(record)
                    self._audit.entry(
                        "tool_blocked",
                        task_id=self._task_id,
                        tool=tool_name,
                        reason="approval_not_found",
                    )
                    return ToolResult(
                        ok=False, error="approval not found for write tool", status="blocked"
                    )
            if not approved_pass:
                if self._approval_service is None:
                    # M1/M2 语义：无审批流时登记幂等键，避免重复生成 pending approval
                    self._seen_keys.add(key)
                # M3-C：审批流中不登记——用户批准后调用方可重试（GT-W01/W03）
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
                    error="dangerous tool blocked: approval required (M3)",
                    status="blocked",
                )

        try:
            data = tool.handler(**args, ctx=ctx) if tool.accepts_ctx else tool.handler(**args)
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
        ts = _now()
        content_hash = hashlib.sha256(str(data).encode()).hexdigest()[:16]
        # 006 十一：Evidence 固化（先固化再返回引用，模型只拿 Evidence ID）
        if self.evidence_writer is not None:
            try:
                self._quota.check_read_bytes(
                    self.evidence_writer, additional=len(str(data).encode("utf-8"))
                )
                source_type = _source_type_of(tool_name)
                source_uri = str(
                    args.get("url")
                    or args.get("repo")
                    or args.get("path")
                    or args.get("source_id")
                    or tool_name
                )
                ev = self.evidence_writer.write(
                    tool_name=tool_name,
                    source_type=source_type,
                    source_uri=source_uri,
                    content=str(data),
                    title=tool.description[:80],
                    subtask_id=ctx.subtask_id if ctx else None,
                    reliability=0.7 if tool.risk_level is RiskLevel.SAFE else 0.5,
                )
                evidence_id = ev.evidence_id
                ts = ev.retrieved_at
                content_hash = ev.content_hash
            except EvidenceQuotaExceeded:
                # Evidence 配额超限：结果不固化（记录仍保留），按 blocked 语义返回
                record["status"] = "blocked"
                self._audit.entry("tool_evidence_quota", task_id=self._task_id, tool=tool_name)
                return ToolResult(ok=False, error="evidence quota exceeded", status="blocked")
            except ValueError as exc:
                # 读取字节配额超限（51）：不固化，按 blocked 语义返回
                record["status"] = "blocked"
                self._audit.entry(
                    "tool_read_quota",
                    task_id=self._task_id,
                    tool=tool_name,
                    error=redact(str(exc))[:200],
                )
                return ToolResult(ok=False, error=f"quota exceeded: {exc}", status="blocked")
        self.evidence.append(
            {
                "id": evidence_id,
                "task_id": self._task_id,
                "tool": tool_name,
                "summary": redact(str(data))[:200],
                "ts": ts,
                "idempotency_key": key,
                "content_hash": content_hash,
            }
        )
        self._result_cache[key] = {
            "data": data,
            "evidence_id": evidence_id,
            "ts": ts,
            "hash": content_hash,
        }
        self._audit.entry(
            "tool_ok", task_id=self._task_id, tool=tool_name, read_only=tool.read_only
        )
        return ToolResult(ok=True, data=data, evidence_id=evidence_id)
