"""权限与审批服务（007 五）：ApprovalService / ApprovalRequest / ApprovalDecision。

- 审批等级：none / preview / explicit / forbidden（映射表见 APPROVAL_FLOW 文档）。
- 批准必须绑定 approval_id + 操作哈希 + 参数哈希 + 目标文件哈希 + 有效期（5.3）。
- 批准后参数变化 → 旧批准立即失效（执行前 re-verify，防 TOCTOU）。
- 决策：approved / rejected / expired / cancelled；重复批准幂等；已拒绝不可再批准。
- 与 LangGraph interrupt 集成：生成提案 → 创建请求 → Checkpoint → paused/awaiting_approval
  → 用户决定 → 恢复 → 再验证操作哈希 → 执行或终止（5.4）。
- ApprovalRequest 不得包含 API Key/Authorization/完整环境变量/未脱敏文件内容/隐藏推理（5.2）。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

DEFAULT_TTL_SECONDS = 3600  # 审批有效期（5.3）


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ApprovalError(Exception):
    """审批错误（安全消息）。"""


def _stable_hash(*parts: str) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:32]


class ApprovalRequest(BaseModel):
    """审批请求（5.2：不得含凭据/未脱敏内容/隐藏推理）。"""

    approval_id: str
    task_id: str
    run_id: str | None = None
    subtask_id: str | None = None
    action_type: (
        str  # write_file | modify_file | delete_path | run_command | apply_patch | git_commit
    )
    tool_name: str = ""
    risk_level: str = "safe"  # safe | sensitive | dangerous
    approval_level: str = "explicit"  # none | preview | explicit | forbidden（5.1）
    summary: str = ""
    target_paths: list[str] = Field(default_factory=list)
    command_argv: list[str] = Field(default_factory=list)
    diff_ref: str | None = None
    estimated_file_changes: int = 0
    estimated_runtime: float = 0.0
    requested_at: str = ""
    status: str = "pending"  # pending | approved | rejected | expired | cancelled
    # 批准绑定（5.3）
    operation_hash: str = ""
    parameter_hash: str = ""
    target_hash: str = ""
    expires_at: str | None = None
    decided_at: str | None = None
    decision_reason: str | None = None

    def model_dump_safe(self) -> dict[str, Any]:
        """API/CLI 展示用（不含内部字段之外的内容；本模型本就不含凭据）。"""
        return self.model_dump()


class ApprovalService:
    """审批服务：创建 / 决策 / 验证（操作哈希绑定，防 TOCTOU）。

    可选持久化（JSONL，跨进程恢复用，007 5.4/十九-11）。
    """

    def __init__(
        self, ttl_seconds: int = DEFAULT_TTL_SECONDS, storage_path: Path | None = None
    ) -> None:
        self._ttl = ttl_seconds
        self._requests: dict[str, ApprovalRequest] = {}
        self._storage_path = storage_path
        if storage_path is not None:
            storage_path.parent.mkdir(parents=True, exist_ok=True)
            self._load()

    # ---- 哈希计算（5.3） ----
    @staticmethod
    def operation_hash_of(
        action_type: str,
        tool_name: str,
        summary: str,
        target_paths: list[str],
        command_argv: list[str] | None = None,
        diff_ref: str | None = None,
    ) -> str:
        return _stable_hash(
            action_type,
            tool_name,
            summary,
            json.dumps(target_paths, sort_keys=True),
            json.dumps(command_argv or [], sort_keys=True),
            diff_ref or "",
        )

    @staticmethod
    def parameter_hash_of(params: dict[str, Any]) -> str:
        return _stable_hash(json.dumps(params, sort_keys=True, default=str))

    @staticmethod
    def target_hash_of(target_files: dict[str, str]) -> str:
        """目标文件内容哈希：{相对路径: sha256 内容}。"""
        return _stable_hash(json.dumps(target_files, sort_keys=True))

    # ---- 生命周期 ----
    def create(
        self,
        *,
        task_id: str,
        run_id: str | None = None,
        subtask_id: str | None = None,
        action_type: str,
        tool_name: str = "",
        risk_level: str = "safe",
        approval_level: str = "explicit",
        summary: str = "",
        target_paths: list[str] | None = None,
        command_argv: list[str] | None = None,
        diff_ref: str | None = None,
        estimated_file_changes: int = 0,
        estimated_runtime: float = 0.0,
        parameter_hash: str = "",
        target_hash: str = "",
    ) -> ApprovalRequest:
        """创建审批请求（4.x 流程：提案 → 请求 → Checkpoint）。"""
        approval_id = uuid.uuid4().hex[:16]
        requested_at = _now()
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=self._ttl)).isoformat()
        request = ApprovalRequest(
            approval_id=approval_id,
            task_id=task_id,
            run_id=run_id,
            subtask_id=subtask_id,
            action_type=action_type,
            tool_name=tool_name,
            risk_level=risk_level,
            approval_level=approval_level,
            summary=summary,
            target_paths=target_paths or [],
            command_argv=command_argv or [],
            diff_ref=diff_ref,
            estimated_file_changes=estimated_file_changes,
            estimated_runtime=estimated_runtime,
            requested_at=requested_at,
            operation_hash=self.operation_hash_of(
                action_type,
                tool_name,
                summary,
                target_paths or [],
                command_argv,
                diff_ref,
            ),
            parameter_hash=parameter_hash,
            target_hash=target_hash,
            expires_at=expires_at,
        )
        self._requests[approval_id] = request
        self._persist(request)
        return request

    def get(self, approval_id: str) -> ApprovalRequest | None:
        return self._requests.get(approval_id)

    def all(self, task_id: str | None = None) -> list[ApprovalRequest]:
        reqs = list(self._requests.values())
        if task_id:
            reqs = [r for r in reqs if r.task_id == task_id]
        return sorted(reqs, key=lambda r: r.requested_at)

    def is_expired(self, request: ApprovalRequest) -> bool:
        if request.expires_at is None:
            return False
        from datetime import datetime

        expires = datetime.fromisoformat(request.expires_at)
        return datetime.now(timezone.utc) > expires

    def decide(self, approval_id: str, decision: str, reason: str | None = None) -> ApprovalRequest:
        """approved / rejected / cancelled（5.3）。已拒绝不可再批准；重复批准幂等。"""
        request = self._requests.get(approval_id)
        if request is None:
            raise ApprovalError(f"approval not found: {approval_id}")
        if self.is_expired(request):
            request.status = "expired"
            raise ApprovalError("approval expired")
        if request.status == "approved" and decision == "approved":
            return request  # 幂等（5.4）
        if request.status == "rejected":
            raise ApprovalError("approval already rejected; cannot re-approve")
        if request.status not in ("pending", "approved"):
            raise ApprovalError(f"approval in state {request.status}; cannot decide")
        if decision not in ("approved", "rejected", "cancelled"):
            raise ApprovalError(f"invalid decision: {decision}")
        request.status = decision
        request.decided_at = _now()
        request.decision_reason = reason
        self._persist(request)
        return request

    def verify_execution(
        self,
        request: ApprovalRequest,
        *,
        parameter_hash: str,
        target_hash: str,
        operation_hash: str | None = None,
    ) -> None:
        """批准后执行前再验证（5.3/5.4：操作哈希/参数哈希/目标哈希绑定；TOCTOU 防护）。

        任一不匹配 → 抛 ApprovalError，执行方必须终止（GT-W04）。
        """
        if request.status != "approved":
            raise ApprovalError(f"approval not approved: {request.status}")
        if self.is_expired(request):
            request.status = "expired"
            raise ApprovalError("approval expired during execution")
        if operation_hash is not None and operation_hash != request.operation_hash:
            raise ApprovalError("operation hash mismatch; approval invalidated")
        if parameter_hash and parameter_hash != request.parameter_hash:
            raise ApprovalError("parameter hash mismatch; approval invalidated (GT-W04)")
        if target_hash and target_hash != request.target_hash:
            raise ApprovalError("target hash mismatch; approval invalidated (GT-W04)")

    # ---- 持久化（跨进程恢复，十九-11） ----
    def _persist(self, request: ApprovalRequest) -> None:
        if self._storage_path is None:
            return
        with self._storage_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(request.model_dump(), ensure_ascii=False) + "\n")

    def _load(self) -> None:
        if self._storage_path is None or not self._storage_path.exists():
            return
        for line in self._storage_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                request = ApprovalRequest(**json.loads(line))
                self._requests[request.approval_id] = request
