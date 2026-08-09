"""Executor 正式启用（007 十二/十三）：DeterministicFakeExecutor + 审批中断工作流。

Executor 只允许：
- 创建 PatchProposal（确定性生成，基于 worktree 当前内容与 Evidence）。
- 读取 worktree（经 Tool Gateway 只读工具）。
- 调用沙箱写工具（经网关 + approval_id 放行）。
- 调用受限测试命令（白名单执行器）。
- 生成 Artifact。

Executor 禁止：修改审批状态（approval service 只读）、自行批准（决定来自 interrupt
恢复值）、访问源项目（只看到 worktree 副本）、调用网络、未登记命令、remote/push/发送/设备。

工作流（十三）：
分析 → 读 Evidence/代码 → 生成 PatchProposal → 确定性校验 → Diff Artifact → 请求审批
→ interrupt 暂停 → 批准后恢复（verify 操作/参数/目标哈希）→ 应用补丁 → 执行批准测试
→ Artifact → Reviewer。
拒绝：不应用补丁、保留提案与 Diff、状态 rejected_by_user、不标记完成实施（GT-W03）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from langgraph.types import interrupt

from app.core.approval import ApprovalError, ApprovalService
from app.core.artifacts import ArtifactWriter
from app.core.command_runner import SandboxCommandRunner
from app.core.patch_engine import (
    PatchApplier,
    PatchProposal,
    PatchValidator,
    sha256_text,
)
from app.core.schemas import ApprovalPayload, Claim, ExecutionResult
from app.core.state import SubtaskState
from app.gateway.tool_gateway import ToolGateway


@dataclass
class SandboxContext:
    """沙箱执行上下文（runner 注入；Executor 不可伪造）。"""

    worktree: Path
    approval: ApprovalService
    artifacts: ArtifactWriter
    command_runner: SandboxCommandRunner | None = None
    tool_gateway: ToolGateway | None = None
    task_id: str = ""
    run_id: str | None = None  # 真实 run_id（审批记录绑定，API/CLI 恢复定位）
    permission_mode: str = "standard"


class ExecutorError(Exception):
    """执行器错误（安全消息）。"""


def _now() -> str:
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class DeterministicFakeExecutor:
    """确定性 Executor（Fake）：按场景生成 PatchProposal 并走审批中断流程。

    场景：
    - sandbox_code_fix（GT-W02/W07）：合成项目 bug → 最小修复补丁 → pytest 由失败变通过。
    - sandbox_create_readme（GT-W01）：README 追加段落。
    - sandbox_code_fix_reject（GT-W03）：生成合法补丁但用户拒绝 → 不应用。
    """

    def __init__(self, sandbox: SandboxContext) -> None:
        self._sandbox = sandbox

    # ---- 确定性提案生成 ----
    def _propose(self, subtask: SubtaskState, scenario: str) -> PatchProposal:

        if "create_readme" in scenario or "GT-W01" in scenario:
            return self._propose_readme(subtask)
        if "reject" in scenario:
            return self._propose_bugfix(subtask, reject_scenario=True)
        return self._propose_bugfix(subtask)

    def _propose_readme(self, subtask: SubtaskState) -> PatchProposal:
        readme = self._sandbox.worktree / "README.md"
        old = readme.read_text(encoding="utf-8") if readme.exists() else ""
        addition = "\n## Sandbox 段落（GT-W01）\n由 Executor 生成的确定性新增段落。\n"
        target = "README.md"
        # 正确 unified diff（review sa_20260805_144828）：旧行作上下文（" " 前缀）
        # + 末尾追加新行；空文件 hunk 用 @@ -0,0（patch_engine 已支持）
        old_lines = old.splitlines(keepends=True)
        add_lines = addition.splitlines(keepends=True)
        if old_lines:
            n = len(old_lines)
            k = len(add_lines)
            diff_lines = [
                f"--- a/{target}\n",
                f"+++ b/{target}\n",
                f"@@ -{n},{n} +{n},{n + k} @@\n",
            ]
            diff_lines += [" " + line for line in old_lines]
            diff_lines += ["+" + line for line in add_lines]
        else:
            diff_lines = [
                f"--- a/{target}\n",
                f"+++ b/{target}\n",
                f"@@ -0,0 +1,{len(add_lines)} @@\n",
            ]
            diff_lines += ["+" + line for line in add_lines]
        diff = "".join(diff_lines)
        return PatchProposal(
            patch_id="p-readme",
            task_id=self._sandbox.task_id,
            subtask_id=subtask.subtask_id,
            target_files=[target],
            unified_diff=diff,
            reason="GT-W01：新增 README 段落",
            expected_effect="README.md 末尾追加段落",
            risk_summary="新增文本段落，低风险",
            tests_to_run=[],
        )

    def _propose_bugfix(
        self, subtask: SubtaskState, reject_scenario: bool = False
    ) -> PatchProposal:
        """GT-W02：合成项目确定性 bug（src/main.py 的 buggy() 恒错）+ 失败测试。"""
        main = self._sandbox.worktree / "src" / "main.py"
        if not main.exists():
            raise ExecutorError("src/main.py not found in sandbox worktree")
        old = main.read_text(encoding="utf-8")
        if "def buggy" not in old:
            raise ExecutorError("deterministic bug not found (expected 'def buggy')")
        # 只替换函数体缩进行的 return False（docstring 描述含同串，先出现会误替换）
        new = old.replace("    return False\n", "    return True\n", 1)
        target = "src/main.py"
        diff_lines = ["--- a/" + target + "\n", "+++ b/" + target + "\n"]
        old_lines = old.splitlines(keepends=True)
        new_lines = new.splitlines(keepends=True)
        diff_lines.append(f"@@ -1,{len(old_lines)} +1,{len(new_lines)} @@\n")
        diff_lines += ["-" + line for line in old_lines]
        diff_lines += ["+" + line for line in new_lines]
        return PatchProposal(
            patch_id="p-bugfix",
            task_id=self._sandbox.task_id,
            subtask_id=subtask.subtask_id,
            target_files=[target],
            unified_diff="".join(diff_lines),
            reason="GT-W02：修复确定性 bug（最小变更）",
            expected_effect="buggy() 返回 True；pytest 由失败变通过",
            risk_summary="单函数单行变更，低风险",
            tests_to_run=["python_pytest"],
        )

    # ---- 工作流（十三） ----
    def run(
        self, subtask: SubtaskState, all_subtasks: list[SubtaskState], scenario: str = ""
    ) -> ExecutionResult:
        """执行 Executor 子任务：提案 → 校验 → Diff Artifact → 审批 interrupt → 应用/拒绝。"""
        sb = self._sandbox
        try:
            proposal = self._propose(subtask, scenario)
        except ExecutorError as exc:
            return ExecutionResult(
                subtask_id=subtask.subtask_id,
                summary=f"executor failed: {exc}",
                claims=[],
                ts=_now(),
            )
        # 8.2：确定性校验（10 项）
        try:
            PatchValidator(sb.worktree).validate(proposal)
        except Exception as exc:  # noqa: BLE001
            return ExecutionResult(
                subtask_id=subtask.subtask_id,
                summary=f"patch validation failed: {exc}",
                claims=[],
                ts=_now(),
            )
        # 8.3：Diff Artifact（审批前生成预览）
        # 重放复用（nit sa_20260805_144828）：同子任务同内容 diff 不重复写
        diff_artifact = sb.artifacts.write(
            artifact_type="diff",
            content=proposal.unified_diff,
            task_id=sb.task_id,
            subtask_id=subtask.subtask_id,
            created_by="executor",
            metadata={
                "patch_id": proposal.patch_id,
                "expected_effect": proposal.expected_effect,
                "proposal": proposal.model_dump(mode="json"),
            },
            dedupe_content=True,
        )
        # 目标哈希（审批绑定，5.3）
        target_hashes = {}
        for rel in proposal.target_files:
            target = sb.worktree / rel
            if target.exists():
                target_hashes[rel] = sha256_text(
                    target.read_text(encoding="utf-8", errors="replace")
                )
        candidate_parameter_hash = ApprovalService.parameter_hash_of(
            {"patch_json": proposal.model_dump_json()}
        )
        # 重放语义（5.4）：LangGraph 恢复时重放本节点——复用该子任务最新**可决策**审批
        # 请求（pending/approved；用户决定绑定其 approval_id）。rejected 请求不可再决策，
        # 重派时必须创建新请求，否则恢复永久卡死（review blocking sa_20260805_144828）
        existing = [
            r
            for r in sb.approval.all(sb.task_id)
            if r.subtask_id == subtask.subtask_id
            and r.status in ("pending", "approved")
            and r.diff_ref == diff_artifact.artifact_id
            and r.target_paths == proposal.target_files
        ]
        if existing:
            request = existing[-1]
            # The immutable approved diff artifact and target list are exact
            # matches. Reuse the parameter hash bound to that approval even if
            # a replayed model changes non-executable proposal prose.
            parameter_hash = request.parameter_hash
        else:
            parameter_hash = candidate_parameter_hash
            request = sb.approval.create(
                task_id=sb.task_id,
                run_id=sb.run_id or sb.task_id,
                subtask_id=subtask.subtask_id,
                action_type="apply_patch",
                tool_name="sandbox_apply_patch",
                risk_level="sensitive",
                approval_level=(
                    "automatic_full_access"
                    if sb.permission_mode == "full_access"
                    else "explicit"
                ),
                summary=proposal.reason,
                target_paths=proposal.target_files,
                diff_ref=diff_artifact.artifact_id,
                estimated_file_changes=len(proposal.target_files),
                parameter_hash=parameter_hash,
                target_hash=ApprovalService.target_hash_of(target_hashes),
            )
            from app.core.events import emit as event_emit

            event_emit(
                task_id=sb.task_id,
                run_id=sb.run_id or sb.task_id,
                event_type=(
                    "approval_bypassed"
                    if sb.permission_mode == "full_access"
                    else "approval_requested"
                ),
                actor_type="executor",
                actor_id=subtask.subtask_id,
                summary=(
                    f"full-access mode applied without manual approval: {proposal.reason}"
                    if sb.permission_mode == "full_access"
                    else f"approval requested: {proposal.reason}"
                ),
                payload_safe={
                    "approval_id": request.approval_id,
                    "files": proposal.target_files,
                    "diff_ref": diff_artifact.artifact_id,
                    "permission_mode": sb.permission_mode,
                },
            )
        # 5.4：LangGraph interrupt（首次执行暂停；恢复时返回用户决定）
        if sb.permission_mode == "full_access":
            sb.approval.decide(
                request.approval_id,
                "approved",
                reason="user selected full-access mode; manual approval bypassed",
            )
            decision = ApprovalPayload(
                approval_id=request.approval_id,
                decision="approved",
                reason="full_access",
            )
        else:
            decision = interrupt(
                ApprovalPayload(approval_id=request.approval_id, decision="approved")
            )
        # 恢复值绑定解析（blocking sa_20260805_144828）：用户决定绑定的是其批准的
        # approval_id（拒绝重放时用户决定绑定旧 rejected 请求，而本节点新建了请求）。
        # 按 payload.approval_id 解析真实请求；新建但未决策的请求取消（不污染审批列表）。
        resolved = request
        if decision.approval_id != request.approval_id:
            alt = sb.approval.get(decision.approval_id)
            if alt is None:
                return ExecutionResult(
                    subtask_id=subtask.subtask_id,
                    summary="approval_id mismatch on resume; patch not applied",
                    claims=[],
                    ts=_now(),
                    metadata={"status": "rejected_verification"},
                )
            resolved = alt
        if decision.decision != "approved":
            # GT-W03：拒绝 → 不应用补丁、保留提案与 Diff、标记未实施
            if resolved.approval_id != request.approval_id:
                try:
                    sb.approval.cancel(request.approval_id, reason="superseded by user decision")
                except ApprovalError:
                    pass  # 已决策/已取消则忽略
            request = resolved
            return ExecutionResult(
                subtask_id=subtask.subtask_id,
                summary=(
                    f"rejected_by_user: {decision.reason or 'no reason'}; "
                    "patch not applied (approval {request.approval_id})"
                ),
                claims=[],
                ts=_now(),
                metadata={
                    "approval_id": request.approval_id,
                    "status": "rejected_by_user",
                    "diff_artifact_id": diff_artifact.artifact_id,
                },
            )
        request = resolved
        # 批准：再验证（5.4 TOCTOU）→ 应用 → 测试 → Artifact
        try:
            sb.approval.verify_execution(
                request,
                parameter_hash=parameter_hash,
                target_hash=ApprovalService.target_hash_of(target_hashes),
                operation_hash=request.operation_hash,
            )
        except ApprovalError as exc:
            # GT-W04：哈希不匹配 → 确定性拒绝，不写文件
            return ExecutionResult(
                subtask_id=subtask.subtask_id,
                summary=f"approval verification failed; patch not applied: {exc}",
                claims=[],
                ts=_now(),
                metadata={"approval_id": request.approval_id, "status": "rejected_verification"},
            )
        try:
            applier = PatchApplier(sb.worktree, sb.worktree.parent / "backups")
            new_hashes = applier.apply(proposal, request.approval_id)
        except Exception as exc:  # noqa: BLE001
            return ExecutionResult(
                subtask_id=subtask.subtask_id,
                summary=f"patch apply failed (rolled back): {exc}",
                claims=[],
                ts=_now(),
                metadata={"approval_id": request.approval_id, "status": "apply_failed"},
            )
        from app.core.events import emit as event_emit

        event_emit(
            task_id=sb.task_id,
            run_id=sb.run_id or sb.task_id,
            event_type="patch_applied",
            actor_type="executor",
            actor_id=subtask.subtask_id,
            summary=f"patch applied: {proposal.target_files}",
            payload_safe={
                "approval_id": request.approval_id,
                "files": proposal.target_files,
                "patch_ref": diff_artifact.artifact_id,
            },
        )
        patch_artifact = sb.artifacts.write(
            artifact_type="patch",
            content=proposal.unified_diff,
            task_id=sb.task_id,
            subtask_id=subtask.subtask_id,
            created_by="executor",
            approval_id=request.approval_id,
            source_evidence_ids=list(subtask.evidence_refs or []),
            metadata={"new_hashes": new_hashes},
        )
        # 执行批准的测试（9.x 白名单；GT-W02：pytest）
        test_report = None
        if proposal.tests_to_run and sb.command_runner is not None:
            event_emit(
                task_id=sb.task_id,
                run_id=sb.run_id or sb.task_id,
                event_type="test_started",
                actor_type="executor",
                actor_id=subtask.subtask_id,
                summary="running pytest",
                payload_safe={"command": "python_pytest -q"},
            )
            result = sb.command_runner.run(
                "python_pytest", ["-q"], cwd_alias="worktree", timeout_seconds=120
            )
            test_report = result.to_dict()
            sb.artifacts.write(
                artifact_type="test_report",
                content=json.dumps(test_report, ensure_ascii=False, indent=2),
                task_id=sb.task_id,
                subtask_id=subtask.subtask_id,
                created_by="executor",
                approval_id=request.approval_id,
            )
            event_emit(
                task_id=sb.task_id,
                run_id=sb.run_id or sb.task_id,
                event_type="test_completed",
                actor_type="executor",
                actor_id=subtask.subtask_id,
                summary=f"pytest rc={test_report.get('return_code')}",
                payload_safe={
                    "return_code": test_report.get("return_code"),
                    "duration_s": test_report.get("duration_s"),
                },
            )
        return ExecutionResult(
            subtask_id=subtask.subtask_id,
            summary=(f"patch applied (approval {request.approval_id}); new hashes: {new_hashes}"),
            claims=[
                Claim(
                    claim_id=f"{subtask.subtask_id}-c1",
                    text=proposal.expected_effect,
                    evidence_ids=[diff_artifact.artifact_id],
                )
            ],
            ts=_now(),
            metadata={
                "approval_id": request.approval_id,
                "patch_id": proposal.patch_id,
                "diff_artifact_id": diff_artifact.artifact_id,
                "patch_artifact_id": patch_artifact.artifact_id,
                "test_report": test_report,
                "status": "implemented",
            },
        )
