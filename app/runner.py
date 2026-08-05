"""任务运行器（M3-A）：真实 Runtime 的创建 / 澄清暂停 / 恢复 / 状态查询 / 追踪。

- 状态持久化：正式 SQLite Checkpointer（thread_id = run_id）。
- 多智能体：M2/M3-A 图（app/graph.py），CLI 与 API 共用本 Runtime。
- 模型模式：fake（默认，DeterministicFakeModel，离线可重复）| real（OpenAI-compatible，
  必须 AI_TEAM_MODEL_ENABLE_REAL=true 且配置 API Key）。
- 预算/工具网关：恢复时以 checkpoint 中的 budget_usage / idempotency_keys 重建（不清零、不重放）。
"""

from __future__ import annotations

import os
import re
import sqlite3
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from app.agents.executor import SandboxContext
from app.core.budget import BudgetController, BudgetExceeded
from app.core.config import AppSettings, allowed_read_roots, load_settings
from app.core.context_builder import ContextBuilder
from app.core.evidence import EvidenceWriter
from app.core.registry import default_registry
from app.core.resume import ResumePayload
from app.core.schemas import ApprovalPayload, ClarificationPayload
from app.core.state import TaskState
from app.gateway.audit import AuditLog
from app.gateway.fake_provider import FakeModelProvider
from app.gateway.model_gateway import DeterministicFakeModel, ModelGateway
from app.gateway.openai_compatible import OpenAICompatibleProvider
from app.gateway.router import ModelRouter, build_router
from app.gateway.tool_gateway import ToolGateway
from app.gateway.tool_policy import ToolPolicy
from app.graph import build_graph
from app.tools.fixture_repo import (
    DangerousWriteTool,
    FixtureRepositoryLookupTool,
    FixtureSourceLookupTool,
)
from app.tools.github_client import GitHubClient
from app.tools.github_tools import build_github_tools
from app.tools.local_file import LocalPathPolicy, build_local_tools
from app.tools.web_fetch import WebFetchTool

DEFAULT_REPO_FIXTURE = Path(__file__).parent / "tools" / "fixtures" / "repos.json"
DEFAULT_SOURCE_FIXTURE = Path(__file__).parent / "tools" / "fixtures" / "sources.json"


@dataclass
class RunReport:
    task_id: str
    run_id: str | None
    state: TaskState
    usage: dict[str, float]
    call_count: int
    tool_call_count: int
    status: str


@dataclass
class RunContext:
    budget: BudgetController
    audit: AuditLog
    provider: object
    model_gateway: ModelGateway
    tool_gateway: ToolGateway
    router: ModelRouter
    context: ContextBuilder
    settings: AppSettings
    local_roots: list = field(default_factory=list)
    sandbox: SandboxContext | None = None  # 007 四-十三：沙箱执行上下文


def build_provider(settings: AppSettings):
    """按配置构造 Provider（005 7.4：real 模式必须显式开启）。"""
    if settings.model.provider == "openai_compatible":
        return OpenAICompatibleProvider(
            base_url=settings.model.base_url,
            api_key=settings.model.api_key,
            default_model=settings.model.default_model,
            enable_real=settings.model.enable_real,
            timeout_seconds=settings.model.timeout_seconds,
            temperature=settings.model.temperature,
            max_output_tokens=settings.model.max_output_tokens,
        )
    return FakeModelProvider()


def _open_conn(data_dir: Path) -> sqlite3.Connection:
    data_dir.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(str(data_dir / "checkpoints.db"), check_same_thread=False)


def _build_context(
    state: TaskState,
    data_dir: Path,
    model_responses: dict[str, str] | None = None,
    settings: AppSettings | None = None,
    model_mode: str = "fake",
    model_overrides: dict[str, str] | None = None,
    run_id: str | None = None,
) -> RunContext:
    """按 checkpoint 状态重建运行时上下文（预算/工具网关带历史，保证不清零、不重放）。"""
    settings = settings or load_settings()
    if model_mode == "real" and not settings.model.enable_real:
        # 005 7.4 / 006 3.2：真实调用必须显式开启，未启用时明确拒绝（不静默进入图内失败）
        from app.gateway.contracts import ProviderError, ProviderErrorCode

        raise ProviderError(
            ProviderErrorCode.CONFIG_ERROR,
            "real model calls disabled; set AI_TEAM_MODEL_ENABLE_REAL=true",
            provider=settings.model.provider,
            model=settings.model.default_model or "",
        )
    budget = BudgetController(
        state.token_budget,
        state.cost_budget,
        initial_usage=state.budget_usage,
    )
    audit = AuditLog(data_dir / "audit.jsonl")
    if model_mode == "real":
        provider = build_provider(settings)
    else:
        provider = DeterministicFakeModel(responses=model_responses)
    model_gateway = ModelGateway(
        provider=provider, budget=budget, audit=audit, task_id=state.task_id
    )
    tool_gateway = ToolGateway(
        audit=audit,
        task_id=state.task_id,
        initial_keys=set(state.idempotency_keys),
        initial_calls=[r.model_dump() for r in state.tool_calls],
        initial_evidence=[e.model_dump() for e in state.evidence],
        initial_approvals=[a.model_dump() for a in state.approvals],
        policy=ToolPolicy(),
        evidence_writer=EvidenceWriter(data_dir / "runtime", state.task_id),
    )
    tool_gateway.register(FixtureRepositoryLookupTool(DEFAULT_REPO_FIXTURE).spec())
    tool_gateway.register(FixtureSourceLookupTool(DEFAULT_SOURCE_FIXTURE).spec())
    tool_gateway.register(DangerousWriteTool().spec())
    # 006 六/七/八：真实只读工具注册（网络工具仅 real 模式注册；本地工具按允许根目录）
    if model_mode == "real":
        for spec in build_github_tools(GitHubClient()):
            tool_gateway.register(spec)
        tool_gateway.register(WebFetchTool().spec())
    roots = allowed_read_roots(settings)
    local_roots: list = []
    if model_overrides and "project_alias" in model_overrides:
        # CLI/API 项目别名 → 允许根目录子目录（14/15：不使用任意绝对路径）
        # 别名严格限字母数字下划线连字符（review sa_20260805_035741 Blocking-2：防穿越）
        alias = model_overrides["project_alias"]
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", alias):
            raise ValueError("project_alias must match [A-Za-z0-9_-]{1,64}")
        checked: list = []
        for r in roots:
            p = (r / alias).resolve()
            r_resolved = r.resolve()
            if p.is_dir() and (
                str(p) == str(r_resolved) or str(p).startswith(str(r_resolved) + os.sep)
            ):
                checked.append(p)
        if checked:
            roots = checked
        elif roots:
            # 显式报错而非静默回退完整根（review nit）
            raise ValueError(f"project alias not found under allowed roots: {alias}")
    if roots:
        policy_obj = LocalPathPolicy(roots)
        for spec in build_local_tools(policy_obj):
            tool_gateway.register(spec)
        local_roots = policy_obj.roots()
    # 模型覆盖仅接受角色键（project_alias/allowed_domains 等非模型键不进入路由）
    model_override_roles = {
        k: v
        for k, v in (model_overrides or {}).items()
        if k in ("supervisor", "planner", "researcher", "reviewer", "executor")
    }
    router = build_router(
        settings, audit=audit, task_id=state.task_id, overrides=model_override_roles or None
    )
    context = ContextBuilder(settings)
    # 007 四-十三：沙箱执行上下文（sandbox_* 目标任务；工作区从磁盘加载或新建）
    sandbox = _build_sandbox_context(
        state, data_dir, tool_gateway, model_overrides, settings, audit, run_id
    )
    return RunContext(
        budget=budget,
        audit=audit,
        provider=provider,
        model_gateway=model_gateway,
        tool_gateway=tool_gateway,
        router=router,
        context=context,
        settings=settings,
        local_roots=local_roots,
        sandbox=sandbox,
    )


def _build_sandbox_context(
    state: TaskState,
    data_dir: Path,
    tool_gateway: ToolGateway,
    model_overrides: dict[str, str] | None,
    settings: AppSettings,
    audit: AuditLog,
    run_id: str | None = None,
) -> SandboxContext | None:
    """构造沙箱上下文（工作区加载/创建 + 审批 + Artifact + 命令执行器 + 写工具注册）。"""
    if not state.user_goal.startswith("sandbox_"):
        return None
    # LOW-2：task_id 拼入工作区路径，严格限 uuid-hex（防路径注入）
    import re as _re

    if not _re.fullmatch(r"[0-9a-f]{12,16}", state.task_id):
        raise ValueError(f"invalid task_id for sandbox workspace: {state.task_id}")
    from app.agents.executor import SandboxContext
    from app.core.approval import ApprovalService
    from app.core.artifacts import ArtifactWriter
    from app.core.command_runner import CommandPolicy, SandboxCommandRunner
    from app.core.workspace import WorkspaceError, WorkspaceManager
    from app.tools.sandbox_tools import SandboxToolset, build_sandbox_tools

    ws_mgr = WorkspaceManager(data_dir / "runtime")
    try:
        manifest = ws_mgr.load_manifest(state.task_id)
    except WorkspaceError:
        alias = (model_overrides or {}).get("project_alias")
        if not alias:
            raise ValueError("sandbox task requires --project <alias> (007 4.2)")
        source = ws_mgr.resolve_project_alias(alias, allowed_read_roots(settings))
        manifest = ws_mgr.create_workspace(state.task_id, alias, source)
    worktree = Path(manifest.worktree_path)
    task_dir = data_dir / "runtime" / "workspaces" / state.task_id
    approval = ApprovalService(storage_path=task_dir / "approvals.jsonl")
    artifacts = ArtifactWriter(data_dir / "runtime", state.task_id)
    command_runner = SandboxCommandRunner(CommandPolicy(), worktree, logs_dir=task_dir / "logs")
    sandbox = SandboxContext(
        worktree=worktree,
        approval=approval,
        artifacts=artifacts,
        command_runner=command_runner,
        tool_gateway=tool_gateway,
        task_id=state.task_id,
        run_id=run_id,
    )
    # 沙箱写工具注册（roles=executor + requires_approval；网关放行需 ctx.approval_id）
    toolset = SandboxToolset(worktree, state.task_id, artifacts, approval)
    for spec in build_sandbox_tools(toolset):
        tool_gateway.register(spec)
    return sandbox


def _compile(ctx: RunContext, state: TaskState, conn: sqlite3.Connection):
    graph = build_graph(
        ctx.model_gateway,
        ctx.tool_gateway,
        goal=state.user_goal,
        registry=default_registry(),
        model_mode=state.model_mode or "fake",
        router=ctx.router,
        context=ctx.context,
        settings=ctx.settings,
        sandbox_context=ctx.sandbox,
    )
    return graph.compile(checkpointer=SqliteSaver(conn))


def run_task(
    goal: str,
    token_budget: int,
    cost_budget: float,
    project_id: str = "default",
    data_dir: Path | None = None,
    model_responses: dict[str, str] | None = None,
    model_mode: str = "fake",
    model_overrides: dict[str, str] | None = None,
    settings: AppSettings | None = None,
) -> RunReport:
    """创建并运行任务（进程 A）。vague_goal 场景在澄清 interrupt 处暂停返回。"""
    data_dir = data_dir or Path("data")
    task_id = uuid.uuid4().hex[:12]
    run_id = uuid.uuid4().hex[:16]
    state = TaskState(
        task_id=task_id,
        run_id=run_id,
        project_id=project_id,
        user_goal=goal,
        token_budget=token_budget,
        cost_budget=cost_budget,
        model_mode=model_mode,
    )
    ctx = _build_context(
        state,
        data_dir,
        model_responses=model_responses,
        settings=settings,
        model_mode=model_mode,
        model_overrides=model_overrides,
        run_id=run_id,
    )
    conn = _open_conn(data_dir)
    try:
        compiled = _compile(ctx, state, conn)
        result = compiled.invoke(state.model_dump(), config={"configurable": {"thread_id": run_id}})
        state = TaskState.model_validate(result)
        if "__interrupt__" in result:
            # 澄清/审批 interrupt：写回 paused（跨进程 status 可读），等待恢复
            interrupt_value = result["__interrupt__"][0].value if result["__interrupt__"] else None
            pending_approval = (
                interrupt_value.approval_id
                if isinstance(interrupt_value, ApprovalPayload)
                else None
            )
            compiled.update_state(
                {"configurable": {"thread_id": run_id}},
                {
                    "current_status": "paused",
                    "paused_from_status": state.current_status,
                    "pending_approval_id": pending_approval,
                },
            )
            state.current_status = "paused"
            state.paused_from_status = state.paused_from_status or "created"
            state.pending_approval_id = pending_approval
            return RunReport(
                task_id,
                run_id,
                state,
                ctx.budget.usage,
                getattr(ctx.provider, "call_count", 0),
                len(ctx.tool_gateway.tool_calls),
                "paused",
            )
        # 图已设置最终状态（completed / failed），runner 不覆盖
    except BudgetExceeded as exc:
        # 失败状态写回 checkpoint（与暂停路径的 update_state 一致），跨进程 status 可读
        state.current_status = "failed"
        state.failure_code = "budget_exceeded"
        state.final_result = str(exc)
        compiled.update_state(
            {"configurable": {"thread_id": run_id}},
            {
                "current_status": "failed",
                "failure_code": "budget_exceeded",
                "final_result": str(exc),
                "budget_usage": ctx.budget.usage,
            },
        )
    finally:
        conn.close()
    return RunReport(
        task_id,
        run_id,
        state,
        ctx.budget.usage,
        getattr(ctx.provider, "call_count", 0),
        len(ctx.tool_gateway.tool_calls),
        state.current_status,
    )


def resume_task(
    run_id: str,
    payload: ResumePayload | ClarificationPayload | ApprovalPayload | None = None,
    data_dir: Path | None = None,
    model_mode: str = "fake",
    model_overrides: dict[str, str] | None = None,
    settings: AppSettings | None = None,
) -> RunReport:
    """从 SQLite checkpoint 恢复（进程 B）。

    - 澄清挂起中：必须提供 ClarificationPayload（004 十三，空答案由 Schema 拒绝）。
    - 审批挂起中：必须提供 ApprovalPayload（007 5.4，approve/reject 先写审批服务再恢复）。
    - 其余场景：ResumePayload（禁止 None，003-A 三/ADR-0001）。
    """
    if payload is None:
        payload = ResumePayload(action="continue")
    data_dir = data_dir or Path("data")
    conn = _open_conn(data_dir)
    try:
        saver = SqliteSaver(conn)
        checkpoint = saver.get_tuple(config={"configurable": {"thread_id": run_id}})
        if checkpoint is None:
            raise KeyError(f"run not found: {run_id}")
        # 恢复前 Schema 校验：未知枚举值 / schema 版本在 TaskState 边界拒绝
        state = TaskState.model_validate(checkpoint.checkpoint["channel_values"])
        # 前置校验：仅 paused 状态可恢复
        if state.current_status != "paused":
            raise RuntimeError(
                f"run {run_id} is not paused "
                f"(current_status={state.current_status!r}); resume rejected"
            )
        # 澄清挂起时恢复值必须为 ClarificationPayload 且 clarification_id 匹配
        if state.pending_clarification_id:
            if not isinstance(payload, ClarificationPayload):
                raise RuntimeError(
                    "run is awaiting clarification; "
                    "provide ClarificationPayload (CLI: --clarification)"
                )
            if payload.clarification_id != state.pending_clarification_id:
                raise RuntimeError(
                    "clarification_id mismatch: "
                    f"{payload.clarification_id} != {state.pending_clarification_id}"
                )
        elif isinstance(payload, ClarificationPayload):
            raise RuntimeError("run is not awaiting clarification")
        # 审批挂起时恢复值必须为 ApprovalPayload 且 approval_id 匹配（007 5.4）
        if state.pending_approval_id:
            if not isinstance(payload, ApprovalPayload):
                raise RuntimeError(
                    "run is awaiting approval; provide ApprovalPayload (approve/reject)"
                )
            if payload.approval_id != state.pending_approval_id:
                raise RuntimeError(
                    f"approval_id mismatch: {payload.approval_id} != {state.pending_approval_id}"
                )
            # 先落审批决策（持久化），恢复后 Executor 再验证并执行/终止
            from app.core.approval import ApprovalService

            approval = ApprovalService(
                storage_path=data_dir / "runtime" / "workspaces" / state.task_id / "approvals.jsonl"
            )
            approval.decide(payload.approval_id, payload.decision, payload.reason)
        elif isinstance(payload, ApprovalPayload):
            raise RuntimeError("run is not awaiting approval")
        ctx = _build_context(
            state,
            data_dir,
            settings=settings,
            model_mode=state.model_mode or model_mode,
            model_overrides=model_overrides,
            run_id=run_id,
        )
        compiled = _compile(ctx, state, conn)
        try:
            result = compiled.invoke(
                Command(resume=payload), config={"configurable": {"thread_id": run_id}}
            )
        except BudgetExceeded as exc:
            # 与 run_task 对称：恢复中预算不足时写回 failed
            compiled.update_state(
                {"configurable": {"thread_id": run_id}},
                {
                    "current_status": "failed",
                    "failure_code": "budget_exceeded",
                    "final_result": str(exc),
                    "budget_usage": ctx.budget.usage,
                },
            )
            state.current_status = "failed"
            state.failure_code = "budget_exceeded"
            state.final_result = str(exc)
            return RunReport(
                state.task_id,
                run_id,
                state,
                ctx.budget.usage,
                getattr(ctx.provider, "call_count", 0),
                len(ctx.tool_gateway.tool_calls),
                "failed",
            )
        state = TaskState.model_validate(result)
        # 图已设置最终状态（completed / failed），runner 不覆盖
        return RunReport(
            state.task_id,
            run_id,
            state,
            ctx.budget.usage,
            getattr(ctx.provider, "call_count", 0),
            len(ctx.tool_gateway.tool_calls),
            state.current_status,
        )
    finally:
        conn.close()


def status_task(run_id: str, data_dir: Path | None = None) -> RunReport:
    """查询任务状态（进程 C）：从 checkpoint 读取，不执行。"""
    data_dir = data_dir or Path("data")
    conn = _open_conn(data_dir)
    try:
        saver = SqliteSaver(conn)
        checkpoint = saver.get_tuple(config={"configurable": {"thread_id": run_id}})
        if checkpoint is None:
            raise KeyError(f"run not found: {run_id}")
        state = TaskState.model_validate(checkpoint.checkpoint["channel_values"])
        return RunReport(
            state.task_id,
            run_id,
            state,
            state.budget_usage,
            0,
            len(state.tool_calls),
            state.current_status,
        )
    finally:
        conn.close()


def trace_task(run_id: str, data_dir: Path | None = None) -> dict:
    """运行追踪（CLI/API trace）：完整结构化状态快照。"""
    data_dir = data_dir or Path("data")
    conn = _open_conn(data_dir)
    try:
        saver = SqliteSaver(conn)
        checkpoint = saver.get_tuple(config={"configurable": {"thread_id": run_id}})
        if checkpoint is None:
            raise KeyError(f"run not found: {run_id}")
        state = TaskState.model_validate(checkpoint.checkpoint["channel_values"])
        return {
            "task_id": state.task_id,
            "run_id": run_id,
            "current_status": state.current_status,
            "failure_code": state.failure_code,
            "model_mode": state.model_mode,
            "clarified_goal": state.clarified_goal,
            "clarification_history": [c.model_dump() for c in state.clarification_history],
            "plan": state.plan,
            "selected_agents": state.selected_agents,
            "subtasks": [s.model_dump() for s in state.subtasks],
            "review_history": [r.model_dump() for r in state.review_history],
            "rework_count": state.rework_count,
            "evidence": [e.model_dump() for e in state.evidence],
            "final_evidence": [e.model_dump() for e in state.final_evidence],
            "tool_call_count": len(state.tool_calls),
            "budget_usage": state.budget_usage,
            "final_result": state.final_result,
        }
    finally:
        conn.close()


def tool_catalog(settings: AppSettings | None = None) -> list[dict]:
    """006 十四：只读工具目录（静态描述，不实例化网络客户端）。"""
    settings = settings or load_settings()
    catalog = [
        {"name": "fixture_repo_lookup", "description": "本地 Fixture 仓库查询", "read_only": True},
        {
            "name": "fixture_source_lookup",
            "description": "本地 Fixture 来源查询",
            "read_only": True,
        },
        {
            "name": "web_fetch",
            "description": "只读获取公开网页内容（SSRF 防护）",
            "read_only": True,
        },
    ]
    catalog.extend(
        {
            "name": s.name,
            "description": s.description,
            "read_only": True,
            "source": "github",
        }
        for s in build_github_tools(GitHubClient())
    )
    roots = allowed_read_roots(settings)
    if roots:
        catalog.extend(
            {
                "name": s.name,
                "description": s.description,
                "read_only": True,
                "source": "local",
            }
            for s in build_local_tools(LocalPathPolicy(roots))
        )
    return catalog


def evidence_list(run_id: str, data_dir: Path | None = None) -> dict:
    """006 十四：任务 Evidence 摘要（不展示快照原文）。"""
    trace = trace_task(run_id, data_dir=data_dir)
    return {
        "run_id": run_id,
        "evidence_count": len(trace["evidence"]),
        "evidence": [
            {
                "evidence_id": e.get("id"),
                "tool": e.get("tool"),
                "source_uri": e.get("source_uri"),
                "summary": e.get("summary", "")[:200],
                "ts": e.get("ts"),
                "truncated": e.get("truncated", False),
            }
            for e in trace["evidence"]
        ],
    }


def workspaces(data_dir: Path | None = None) -> list[dict]:
    """007 十六：列出全部任务工作区（manifest 摘要）。"""
    from app.core.workspace import WorkspaceManager

    return WorkspaceManager((data_dir or Path("data")) / "runtime").workspaces()


def workspace_status(task_id: str, data_dir: Path | None = None) -> dict:
    """007 十六：单个工作区状态（manifest + 目录结构）。"""
    from app.core.workspace import WorkspaceManager

    mgr = WorkspaceManager((data_dir or Path("data")) / "runtime")
    manifest = mgr.load_manifest(task_id)
    base = (data_dir or Path("data")) / "runtime" / "workspaces" / task_id
    return {
        "manifest": manifest.to_dict(),
        "dirs": {
            "input": (base / "input").exists(),
            "worktree": (base / "worktree").exists(),
            "artifacts": (base / "artifacts").exists(),
            "backups": (base / "backups").exists(),
            "logs": (base / "logs").exists(),
        },
    }


def approvals_of(run_id: str, data_dir: Path | None = None) -> list[dict]:
    """007 十六/十七：任务的审批列表（approval_id/状态/摘要——不含凭据）。"""
    from app.core.approval import ApprovalService

    data_dir = data_dir or Path("data")
    checkpoint = _load_checkpoint(run_id, data_dir)
    state = TaskState.model_validate(checkpoint)
    approval = ApprovalService(
        storage_path=data_dir / "runtime" / "workspaces" / state.task_id / "approvals.jsonl"
    )
    return [r.model_dump() for r in approval.all(state.task_id)]


def approval_show(approval_id: str, data_dir: Path | None = None) -> dict:
    """007 十六/十七：单个审批详情（ApprovalRequest 全字段——不含凭据）。"""
    from app.core.approval import ApprovalService

    data_dir = data_dir or Path("data")
    for path in sorted(data_dir.glob("runtime/workspaces/*/approvals.jsonl")):
        svc = ApprovalService(storage_path=path)
        req = svc.get(approval_id)
        if req is not None:
            return req.model_dump()
    raise KeyError(f"approval not found: {approval_id}")


def diff_of(run_id: str, data_dir: Path | None = None) -> dict:
    """007 十六/十七：任务最新 Diff（diff Artifact 内容）。"""
    from app.core.artifacts import ArtifactWriter

    data_dir = data_dir or Path("data")
    checkpoint = _load_checkpoint(run_id, data_dir)
    state = TaskState.model_validate(checkpoint)
    writer = ArtifactWriter(data_dir / "runtime", state.task_id)
    diffs = [a for a in writer.load_all(state.task_id) if a.artifact_type == "diff"]
    if not diffs:
        return {"ok": False, "error": "no diff artifact found"}
    latest = diffs[-1]
    return {"ok": True, "artifact_id": latest.artifact_id, "diff": writer.read_content(latest)}


def artifacts_of(run_id: str, data_dir: Path | None = None) -> list[dict]:
    """007 十六/十七：任务 Artifact 列表。"""
    from app.core.artifacts import ArtifactWriter

    data_dir = data_dir or Path("data")
    checkpoint = _load_checkpoint(run_id, data_dir)
    state = TaskState.model_validate(checkpoint)
    writer = ArtifactWriter(data_dir / "runtime", state.task_id)
    return [r.model_dump() for r in writer.load_all(state.task_id)]


def artifact_show(artifact_id: str, data_dir: Path | None = None) -> dict:
    """007 十六/十七：单个 Artifact 内容。"""
    from app.core.artifacts import ArtifactWriter

    data_dir = data_dir or Path("data")
    for task_dir in sorted(data_dir.glob("runtime/workspaces/*")):
        writer = ArtifactWriter(data_dir / "runtime", task_dir.name)
        rec = writer.get(artifact_id, task_dir.name)
        if rec is not None:
            return {"artifact": rec.model_dump(), "content": writer.read_content(rec)}
    raise KeyError(f"artifact not found: {artifact_id}")


def rollback(
    run_id: str, patch_approval_id: str, approval_id: str, data_dir: Path | None = None
) -> dict:
    """007 十六/十七：回滚指定 Patch（须提供已批准的回滚审批）。"""
    from app.core.approval import ApprovalService
    from app.core.artifacts import ArtifactWriter
    from app.core.rollback import WorkspaceRollback
    from app.core.workspace import WorkspaceManager

    data_dir = data_dir or Path("data")
    checkpoint = _load_checkpoint(run_id, data_dir)
    state = TaskState.model_validate(checkpoint)
    ws_mgr = WorkspaceManager(data_dir / "runtime")
    manifest = ws_mgr.load_manifest(state.task_id)
    worktree = Path(manifest.worktree_path)
    base = data_dir / "runtime" / "workspaces" / state.task_id
    approval = ApprovalService(storage_path=base / "approvals.jsonl")
    rollback = WorkspaceRollback(
        worktree,
        base / "input",
        worktree.parent / "backups",
        worktree.parent / "trash",
        ArtifactWriter(data_dir / "runtime", state.task_id),
        approval,
        state.task_id,
    )
    return rollback.rollback_patch(approval_id, patch_approval_id)


def _load_checkpoint(run_id: str, data_dir: Path) -> dict:
    """读取 checkpoint 状态（只读辅助）。"""
    from langgraph.checkpoint.sqlite import SqliteSaver

    conn = _open_conn(data_dir)
    try:
        saver = SqliteSaver(conn)
        checkpoint = saver.get_tuple(config={"configurable": {"thread_id": run_id}})
        if checkpoint is None:
            raise KeyError(f"run not found: {run_id}")
        return checkpoint.checkpoint["channel_values"]
    finally:
        conn.close()


def evidence_show(evidence_id: str, data_dir: Path | None = None) -> dict:
    """006 十四：Evidence 原始快照（明确命令；快照已脱敏，无凭据）。

    evidence_id 严格限十六进制（uuid hex，review sa_20260805_035741 should-fix-1：
    防 glob 穿越读任意文件）。
    """
    if not re.fullmatch(r"[0-9a-f]{16,32}", evidence_id):
        raise KeyError(f"invalid evidence_id: {evidence_id}")
    data_dir = data_dir or Path("data")
    runtime_dir = data_dir / "runtime" / "evidence"
    matches = list(runtime_dir.glob(f"*/{evidence_id}.*"))
    if not matches:
        raise KeyError(f"evidence not found: {evidence_id}")
    path = matches[0]
    return {
        "evidence_id": evidence_id,
        "snapshot": path.read_text(encoding="utf-8", errors="replace")[:100_000],
        "snapshot_ref": path.relative_to(data_dir).as_posix(),
        "size": path.stat().st_size,
    }


def provider_health(settings: AppSettings | None = None) -> dict:
    """Provider 健康（005 十二/十六）：不发起真实请求。"""
    settings = settings or load_settings()
    provider = build_provider(settings)
    health = provider.health_check()
    return {
        "provider": health.provider,
        "status": health.status,
        "model": health.model,
        "message": health.message,
        "checked_at": health.checked_at,
        "real_enabled": settings.model.enable_real,
    }


def dry_run(
    goal: str,
    token_budget: int,
    cost_budget: float,
    settings: AppSettings | None = None,
) -> dict:
    """dry-run（005 十六）：显示预计模型调用与预算，不真正调用。"""
    settings = settings or load_settings()
    from app.graph import plan_scenario_for

    scenario = plan_scenario_for(goal)
    if scenario == "parallel_three_topics":
        research_calls = 3
    elif scenario == "github_compare_plan":
        research_calls = 3
    else:
        research_calls = 1
    roles = {
        "planner": 1,
        "researcher": research_calls,
        "reviewer": research_calls,
        "supervisor": 1,
    }
    calls: list[dict[str, object]] = []
    router = build_router(settings)
    for role, count in roles.items():
        model = router.resolve(role)
        calls.append({"role": role, "model": model or "(default)", "expected_calls": count})
    estimated_tokens = sum(
        int(str(c["expected_calls"])) * settings.model.max_output_tokens * 2 for c in calls
    )
    return {
        "goal": goal,
        "mode": "dry-run",
        "real_enabled": settings.model.enable_real,
        "provider": settings.model.provider,
        "model_calls": calls,
        "estimated_max_tokens": estimated_tokens,
        "token_budget": token_budget,
        "cost_budget": cost_budget,
        "note": "dry-run 不发起任何真实模型调用",
    }
