"""M2 确定性多智能体图（004）。

目标 → 澄清 → 结构化规划 → 确定性派发 → 专家并行执行 → 独立审查 → 定向返工 → 最终汇总。

- 所有角色切换由 LangGraph 边和确定性路由函数执行（004 七）。
- 并行经 LangGraph 官方 Send fan-out/fan-in，禁止自研线程池（004 八）。
- 澄清经 interrupt + ClarificationPayload（004 十三）。
- Supervisor 为确定性调度节点 + 有限模型决策，不直接调用业务工具。
"""

from __future__ import annotations

from datetime import datetime, timezone

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send, interrupt

from app.agents.executor import DeterministicFakeExecutor, SandboxContext
from app.agents.llm_agents import (
    LLMExecutor,
    LLMPlanner,
    LLMResearcher,
    LLMReviewer,
    LLMSupervisorDecision,
)
from app.agents.planner import make_plan
from app.agents.researcher import FakeResearcher
from app.agents.reviewer import (
    DeterministicReviewer,
    FakeReviewer,
    evidence_ids_of,
    max_rework_for,
    role_used_tool_calls,
)
from app.core.completion import ProductCompletionValidator
from app.core.complexity import TaskComplexity, classify_task
from app.core.config import AppSettings
from app.core.context_builder import ContextBuilder
from app.core.orchestration import (
    PlanningEnvelope,
    RoleRouter,
    TaskShape,
    bounded_plan_for_shape,
    deterministic_simplification,
)
from app.core.plan_validator import EXECUTABLE_ROLES, PlanValidationError, validate_plan
from app.core.registry import AgentRegistry, default_registry
from app.core.rework_guard import ReworkProgressGuard, failure_signature
from app.core.schemas import (
    ClarificationPayload,
    ClarificationRecord,
    FinalReport,
    Plan,
    ReviewResult,
    ReviewStatus,
    SubtaskSpec,
)
from app.core.state import CHECKPOINT_VERSION, SubtaskState, TaskState
from app.gateway.contracts import ProviderError
from app.gateway.model_gateway import ModelGateway
from app.gateway.router import ModelRouter
from app.gateway.tool_gateway import ToolGateway

MAX_CLARIFICATION_ROUNDS = 3  # 集中配置（004 十三）
PLAN_RETRY_LIMIT = 2  # 集中配置（004 六）
REPLAN_LIMIT = 2  # PRODUCT-01：Supervisor replan 上限（换方法仍无进展则停止）
# PRODUCT-01（020-B 十五）：subtask 数量按复杂度钳制（简单任务不过度编排）
_MAX_SUBTASKS_BY_COMPLEXITY = {"trivial": 1, "simple": 2, "standard": 4, "complex": 6}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _direct_response(goal: str) -> str:
    """Deterministic responses for runtime facts that need no model or tools."""
    text = (goal or "").strip().lower()
    if any(marker in text for marker in ("你可以干什么", "你能做什么", "what can you do")):
        return (
            "我可以在你设定的权限、安全、预算和工作区边界内，回答问题、调研资料、"
            "分析与修改代码、运行测试，并协调 Planner、Executor 和 Reviewer 完成任务。"
        )
    if any(marker in text for marker in ("介绍一下你自己", "你是谁", "who are you")):
        return (
            "我是 AI Team OS 的 JARVIS 助手。我可以在权限、预算、工作区和审计边界内，"
            "协调研究、代码修改、测试与 Reviewer 完成任务。"
        )
    if any(marker in text for marker in ("几点", "时间", "what time")):
        return f"当前系统时间：{datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}。"
    if any(marker in text for marker in ("日期", "几号", "date today")):
        return f"今天是 {datetime.now().astimezone().strftime('%Y-%m-%d')}。"
    if any(marker in text for marker in ("你好", "hello", "hi")):
        return "你好，我是 JARVIS。你可以直接告诉我想了解或想完成的事情。"
    return "任务已接收；当前请求不需要调用外部工具。"


def plan_scenario_for(goal: str) -> str:
    """goal → Plan 场景。仅显式 "scenario:<name>" 前缀触发负面/测试场景，
    普通生产目标一律走 github_compare_plan（避免误触发 planning_invalid 等）。"""
    if goal.startswith("scenario:"):
        s = goal[len("scenario:") :]
        if s == "parallel":
            return "parallel_three_topics"
        if s == "cycle":
            return "invalid_cycle_plan"
        if s == "over-budget":
            return "over_budget_plan"
        if s == "unknown-agent":
            return "unknown_agent_plan"
    if goal.startswith("sandbox_"):
        # 007：沙箱目标任务（GT-W01~W10）
        if "create_readme" in goal or "GT-W01" in goal:
            return "sandbox_create_readme_plan"
        return "sandbox_code_fix_plan"  # GT-W02/W03/W04/W07/W09 共用
    return "github_compare_plan"


def review_scenario_for(goal: str) -> str:
    """goal → Reviewer 场景（GT-11 / 004 4.2 工具型返工）。仅显式 "scenario:" 前缀触发。"""
    if goal.startswith("scenario:reject-once"):
        return "review_reject_once_then_pass"
    if goal.startswith("scenario:reject-tool-once"):
        return "review_reject_tool_once"
    if goal.startswith("scenario:always-reject"):
        return "review_always_reject"
    return "default"


def needs_clarification(goal: str) -> bool:
    """确定性模糊判定（004 十三）：超短/无结构目标需要澄清。

    PRODUCT-01：TRIVIAL（问候/时间/日期）与 SIMPLE（单步信息型，如"总结这个项目"）
    一句话任务意图自足，即使长度 < 8 也不需要澄清；仅真正的模糊短目标
    （无动词/无对象，如 "x"、"帮我做个东西"）才澄清。
    """
    stripped = goal.strip()
    if stripped in {"帮我做个东西", "vague_goal", "做点东西"}:
        return True
    if len(stripped) < 8:
        return classify_task(stripped) not in (
            TaskComplexity.TRIVIAL,
            TaskComplexity.SIMPLE,
        )
    return False


def build_graph(
    model_gateway: ModelGateway,
    tool_gateway: ToolGateway,
    goal: str = "",
    registry: AgentRegistry | None = None,
    model_mode: str = "fake",
    router: ModelRouter | None = None,
    context: ContextBuilder | None = None,
    settings: AppSettings | None = None,
    sandbox_context: SandboxContext | None = None,
) -> StateGraph:
    """M2/M3-A 图。goal 用于推导 Plan/Reviewer 场景（测试与 CLI 共用同一 Runtime）。

    model_mode: "fake"（默认，DeterministicFake 角色）| "real"（LLM 角色，
    经 Model Gateway + 结构化输出治理；路由/循环/完成条件仍由代码负责，005 15）。
    """
    registry = registry or default_registry()
    plan_scenario = plan_scenario_for(goal)
    review_scenario = review_scenario_for(goal)
    researcher = FakeResearcher(tool_gateway)
    det_reviewer = DeterministicReviewer()
    fake_reviewer = FakeReviewer(review_scenario)
    _guard = ReworkProgressGuard()  # PRODUCT-01：无进展检测（纠偏令 017）
    _completion = ProductCompletionValidator()
    _role_router = RoleRouter()

    def _simple_research_plan(goal_text: str, task_token_budget: int) -> Plan:
        """SIMPLE fast path: one bounded Researcher, no Planner or model Reviewer."""
        budget = max(500, min(2000, task_token_budget // 4))
        return Plan(
            goal=goal_text,
            subtasks=[
                SubtaskSpec(
                    subtask_id="st1",
                    title="完成单步研究",
                    objective=goal_text,
                    dependencies=[],
                    assigned_role="researcher",
                    # Offline fixtures exercise multi-item evidence collection in
                    # the same specialist turn. Real mode chooses a governed tool
                    # from the objective and may return multiple search results.
                    input_refs=[
                        "fixture_repo_lookup:langgraph",
                        "fixture_repo_lookup:crewai",
                    ],
                    expected_output="研究结论（每条带 evidence）",
                    acceptance_criteria=["完成用户要求", "每条已验证结论带 evidence"],
                    required_tools=["fixture_repo_lookup"],
                    token_budget=budget,
                    tool_call_budget=3,
                )
            ],
        )

    settings = settings or AppSettings()
    router = router or ModelRouter(settings.routing)
    context = context or ContextBuilder(settings)
    executor_agent = None
    if sandbox_context is not None:
        executor_agent = (
            LLMExecutor(
                sandbox_context,
                model_gateway,
                router,
                context,
                settings,
                tool_gateway,
            )
            if model_mode == "real"
            else DeterministicFakeExecutor(sandbox_context)
        )
    llm_planner = (
        LLMPlanner(model_gateway, router, context, settings, registry)
        if model_mode == "real"
        else None
    )
    llm_researcher = (
        LLMResearcher(model_gateway, router, context, settings, tool_gateway)
        if model_mode == "real"
        else None
    )
    llm_reviewer = (
        LLMReviewer(model_gateway, router, context, settings) if model_mode == "real" else None
    )
    llm_supervisor = (
        LLMSupervisorDecision(model_gateway, router, context, settings)
        if model_mode == "real"
        else None
    )

    def _validate_checkpoint(state: TaskState) -> None:
        if state.checkpoint_version != CHECKPOINT_VERSION:
            raise RuntimeError(
                f"checkpoint version mismatch: {state.checkpoint_version} != {CHECKPOINT_VERSION}"
            )

    # ---------- 节点 ----------
    def ingest(state: TaskState) -> dict:
        _validate_checkpoint(state)
        if needs_clarification(state.user_goal):
            if len(state.clarification_history) >= MAX_CLARIFICATION_ROUNDS:
                # 004 十三：最多澄清 3 轮，超过后停止并说明信息不足
                return {
                    "current_status": "failed",
                    "failure_code": "information_insufficient",
                    "final_result": f"澄清 {MAX_CLARIFICATION_ROUNDS} 轮后信息仍不足，停止",
                }
            return {"pending_clarification_id": f"cl-{len(state.clarification_history) + 1}"}
        return {"pending_clarification_id": None}

    def route_ingest(state: TaskState) -> str:
        if state.current_status == "failed":
            return "end"
        if state.pending_clarification_id:
            return "clarify"
        return "plan"

    def clarify(state: TaskState) -> dict:
        # interrupt() 首次执行抛 GraphInterrupt 暂停（占位默认值，恢复时返回 payload）
        payload = interrupt(
            ClarificationPayload(
                clarification_id=state.pending_clarification_id or "",
                answer="待澄清",
            )
        )
        record = ClarificationRecord(
            clarification_id=payload.clarification_id,
            question=f"请说明目标 '{state.user_goal}' 要解决什么问题、期望产出什么？",
            answer=payload.answer,
            ts=_now(),
        )
        base = state.clarified_goal or state.user_goal
        clarified_goal = f"{base}（澄清 {payload.clarification_id}：{payload.answer}）"
        return {
            "clarification_history": [record],
            "clarified_goal": clarified_goal,
            "pending_clarification_id": None,
        }

    def plan(state: TaskState) -> dict:
        goal_text = state.clarified_goal or state.user_goal
        complexity = classify_task(goal_text)
        envelope = PlanningEnvelope.for_task(
            goal_text,
            complexity,
            tool_gateway.available_tools(),
            state.token_budget,
            state.max_model_calls,
        )
        replanning = state.replan_reason is not None
        from app.core.events import emit as event_emit

        if replanning:
            # PRODUCT-01（纠偏令 017）：replan 仍无进展 → 停止，禁止 replan 死循环
            if state.replan_count >= REPLAN_LIMIT:
                return {
                    "current_status": "failed",
                    "failure_code": "rework_limit_exceeded",
                    "final_result": (
                        f"Supervisor replan 超过上限 {REPLAN_LIMIT}"
                        f"（最近返工无进展），停止：{state.replan_reason}"
                    ),
                    "replan_reason": None,
                }
        else:
            event_emit(
                task_id=state.task_id,
                run_id=state.run_id,
                event_type="complexity_classified",
                actor_type="supervisor",
                actor_id="supervisor",
                summary=f"task complexity: {complexity.value}",
                payload_safe={"complexity": complexity.value},
            )
        # PRODUCT-01（纠偏令 020-021）：TRIVIAL 一句话问答 → 空计划直接收尾，
        # 不经 Planner / Researcher / Reviewer（finalize 在空计划下直接完成）。
        if complexity == TaskComplexity.TRIVIAL and not replanning:
            return {
                "subtasks": [],
                "selected_agents": {},
                "current_status": "planning",
                "complexity": "trivial",
                "task_shape": envelope.task_shape.value,
                "planning_envelope": envelope.model_dump(mode="json"),
                "review_required": False,
                "replan_reason": None,
            }
        # PRODUCT-01（纠偏令 021/024/027）：SIMPLE 单步研究 → 单 researcher 子任务，
        # 不调 LLM Planner、不配 Reviewer Gate；确定性 Reviewer 仍检查 evidence。
        if complexity == TaskComplexity.SIMPLE and not replanning:
            plan_obj = _simple_research_plan(goal_text, state.token_budget)
            validate_plan(plan_obj, registry, state.token_budget)
            subtasks = [SubtaskState(**s.model_dump()) for s in plan_obj.subtasks]
            event_emit(
                task_id=state.task_id,
                run_id=state.run_id,
                event_type="plan_created",
                actor_type="planner",
                actor_id="planner",
                summary=f"plan created: {len(subtasks)} subtask(s) (simple fast path)",
                payload_safe={"subtask_count": len(subtasks), "complexity": "simple"},
            )
            return {
                "plan": plan_obj.model_dump(),
                "subtasks": subtasks,
                "selected_agents": {s.subtask_id: s.assigned_role for s in plan_obj.subtasks},
                "current_status": "planning",
                "complexity": "simple",
                "task_shape": envelope.task_shape.value,
                "planning_envelope": envelope.model_dump(mode="json"),
                "review_required": False,
                "replan_reason": None,
            }
        # STANDARD / COMPLEX / replan：完整规划。
        # LLM Planner 只看到可执行角色（PRODUCT-01：杜绝 unsupported role 计划）。
        # 简单任务不过度编排（020-B 十五）：subtask 数量按复杂度钳制。
        max_subtasks = _MAX_SUBTASKS_BY_COMPLEXITY.get(complexity.value, 8)
        last_error: PlanValidationError | ProviderError | None = None
        if llm_planner is not None and not replanning:
            try:
                plan_obj = llm_planner.make_plan(
                    state,
                    [
                        a.agent_id
                        for a in registry.all()
                        if a.enabled and a.role_type in EXECUTABLE_ROLES
                    ],
                    max_subtasks=max_subtasks,
                    envelope=envelope,
                )
                for item in plan_obj.subtasks:
                    item.assigned_role = _role_router.route(item.capability_required or "research")
                validate_plan(plan_obj, registry, state.token_budget, envelope=envelope)
                subtasks = [SubtaskState(**s.model_dump()) for s in plan_obj.subtasks]
                event_emit(
                    task_id=state.task_id,
                    run_id=state.run_id,
                    event_type="plan_created",
                    actor_type="planner",
                    actor_id="planner",
                    summary=f"plan created: {len(subtasks)} subtasks",
                    payload_safe={"subtask_count": len(subtasks)},
                )
                return {
                    "plan": plan_obj.model_dump(),
                    "subtasks": subtasks,
                    "selected_agents": {s.subtask_id: s.assigned_role for s in plan_obj.subtasks},
                    "current_status": "planning",
                    "complexity": complexity.value,
                    "task_shape": envelope.task_shape.value,
                    "planning_envelope": envelope.model_dump(mode="json"),
                    "replan_reason": None,
                    "review_required": envelope.task_shape
                    not in {
                        TaskShape.READ_ONLY_RESEARCH,
                        TaskShape.CODE_ANALYSIS,
                    },
                }
            except (PlanValidationError, ProviderError) as exc:  # noqa: PERF203
                last_error = exc
                event_emit(
                    task_id=state.task_id,
                    run_id=state.run_id,
                    event_type="supervisor_replanned",
                    actor_type="supervisor",
                    actor_id="supervisor",
                    summary=f"LLM plan invalid ({getattr(exc, 'code', type(exc).__name__)}); "
                    "Supervisor 切换为确定性 replan",
                    payload_safe={"reason": str(exc)[:500]},
                )
        # Supervisor 换方法（纠偏令 018）：确定性 replan 保证角色/依赖/预算合法。
        try:
            legacy_fake_plan = model_mode == "fake"
            plan_obj = (
                make_plan(plan_scenario, goal_text, task_token_budget=state.token_budget)
                if legacy_fake_plan
                else bounded_plan_for_shape(goal_text, envelope)
                or make_plan(plan_scenario, goal_text, task_token_budget=state.token_budget)
            )
            for item in plan_obj.subtasks:
                item.assigned_role = _role_router.route(item.capability_required or "research")
            try:
                validate_plan(
                    plan_obj,
                    registry,
                    state.token_budget,
                    envelope=None if legacy_fake_plan else envelope,
                )
            except PlanValidationError as exc:
                if exc.code != "plan_too_complex":
                    raise
                plan_obj = deterministic_simplification(plan_obj, envelope)
                validate_plan(
                    plan_obj,
                    registry,
                    state.token_budget,
                    envelope=None if legacy_fake_plan else envelope,
                )
            subtasks = [SubtaskState(**s.model_dump()) for s in plan_obj.subtasks]
            if replanning:
                # 旧计划全部作废：与新 subtask_id 不冲突的旧子任务标记 superseded，
                # 调度/审查/汇总不再处理（LangGraph reducer 按 id 合并，无法删除）。
                new_ids = {s.subtask_id for s in subtasks}
                superseded_old = [
                    s.model_copy(update={"superseded": True})
                    for s in state.subtasks
                    if s.subtask_id not in new_ids
                ]
                subtasks = [*subtasks, *superseded_old]
            if replanning or last_error is not None:
                event_emit(
                    task_id=state.task_id,
                    run_id=state.run_id,
                    event_type="supervisor_replanned",
                    actor_type="supervisor",
                    actor_id="supervisor",
                    summary=f"replanned with {len(subtasks)} subtasks",
                    payload_safe={"replan_reason": state.replan_reason or "plan_invalid_after_llm"},
                )
            event_emit(
                task_id=state.task_id,
                run_id=state.run_id,
                event_type="plan_created",
                actor_type="planner",
                actor_id="planner",
                summary=f"plan created: {len(subtasks)} subtasks",
                payload_safe={"subtask_count": len(subtasks), "source": "deterministic"},
            )
            return {
                "plan": plan_obj.model_dump(),
                "subtasks": subtasks,
                "selected_agents": {s.subtask_id: s.assigned_role for s in plan_obj.subtasks},
                "current_status": "planning",
                "complexity": complexity.value,
                "task_shape": envelope.task_shape.value,
                "planning_envelope": envelope.model_dump(mode="json"),
                "replan_reason": None,
                "replan_count": state.replan_count + (1 if replanning else 0),
                "review_required": envelope.task_shape
                not in {
                    TaskShape.READ_ONLY_RESEARCH,
                    TaskShape.CODE_ANALYSIS,
                },
            }
        except (PlanValidationError, ProviderError) as exc:  # noqa: PERF203
            last_error = exc
        # 超过重试上限：进入 failed/planning_invalid，不得绕过 Schema 继续（004 六 / 005 15.1）
        return {
            "current_status": "failed",
            "failure_code": "planning_invalid",
            "final_result": f"plan invalid after supervisor replan: {last_error}",
            "replan_reason": None,
        }

    def route_plan(state: TaskState) -> str:
        return "end" if state.current_status == "failed" else "dispatch"

    def dispatch(state: TaskState) -> dict:
        """确定性派发入口：Send fan-out 由条件边 route_dispatch 返回（LangGraph 官方模式）。"""
        return {}

    def route_dispatch(state: TaskState) -> list[Send] | str:
        """确定性派发（004 七/八）：仅派发 pending/rejected 且依赖已 passed 的子任务。

        Send payload 携带执行所需完整数据（节点输入为 payload，不经父状态 channel 写入，
        并行 Send 互不冲突；官方 reducer 只用于节点返回的 subtasks 分片合并）。
        """
        by_id = {s.subtask_id: s for s in state.subtasks}
        sends: list[Send] = []
        for s in state.subtasks:
            if s.superseded or s.runtime_status not in ("pending", "rejected"):
                continue
            deps_ok = all(by_id[d].runtime_status == "passed" for d in s.dependencies)
            if deps_ok:
                sends.append(
                    Send(
                        "exec_subtask",
                        {
                            "current_subtask_id": s.subtask_id,
                            "exec_payload": {
                                "subtask": s.model_dump(),
                                "all_subtasks": [x.model_dump() for x in state.subtasks],
                                "review_scenario": review_scenario,
                                "task_id": state.task_id,
                                "run_id": state.run_id,
                            },
                        },
                    )
                )
        if not sends:
            return "review_all"  # 防御：无待派发子任务时直接进入 fan-in 审查
        return sends

    def exec_subtask(state: dict) -> dict:
        """专家并行执行（Send 目标）。输入为 Send payload（dict）；按 subtask_id 分片
        写入，官方 merge_subtasks reducer 合并（004 八）。"""
        payload = state.get("exec_payload") or {}
        subtask = SubtaskState.model_validate(payload["subtask"])
        all_subtasks = [SubtaskState.model_validate(x) for x in payload["all_subtasks"]]
        scenario = payload.get("review_scenario") or review_scenario
        task_id = payload.get("task_id") or payload.get("subtask_id") or "unknown"
        run_id = payload.get("run_id") or task_id
        running = subtask.model_copy(update={"runtime_status": "running"})
        from app.core.events import emit as event_emit

        event_emit(
            task_id=task_id,
            run_id=run_id,
            event_type="subtask_started",
            actor_type=running.assigned_role,
            actor_id=subtask.subtask_id,
            summary=f"subtask started: {subtask.title}",
            payload_safe={"subtask_id": subtask.subtask_id, "role": running.assigned_role},
        )
        if running.assigned_role == "executor":
            # 007 十二/十三：Executor 工作流（审批 interrupt 在此节点内）
            if executor_agent is None:
                updated = running.model_copy(
                    update={
                        "runtime_status": "rejected",
                        "rework_count": running.rework_count + 1,
                        "rework_signatures": running.rework_signatures
                        + [
                            failure_signature(
                                subtask.subtask_id,
                                subtask.assigned_role,
                                None,
                                ["executor_unavailable"],
                            )
                        ],
                    }
                )
                executor_extra: dict[str, str] = {}
                if _guard.has_no_progress(updated.rework_signatures):
                    # PRODUCT-01：连续无进展 → 停止盲重试，Supervisor replan
                    executor_extra = {"replan_reason": f"rework_no_progress: {subtask.subtask_id}"}
                return {"subtasks": [updated], **executor_extra, **tool_gateway.snapshot()}
            verified_dependency = next(
                (
                    item.execution_result
                    for item in all_subtasks
                    if item.subtask_id in running.dependencies
                    and item.execution_result is not None
                    and item.assigned_role == "executor"
                    and item.execution_result.metadata.get("status")
                    in {"implemented", "implemented_replay"}
                    and isinstance(item.execution_result.metadata.get("test_report"), dict)
                    and item.execution_result.metadata["test_report"].get("return_code") == 0
                ),
                None,
            )
            if running.capability_required == "verification" and verified_dependency is not None:
                # A verification/reporting node consumes the immutable patch and
                # passing test evidence from its dependency. It must not apply the
                # same diff or rerun the same command merely because Planner split
                # delivery into multiple terminal steps.
                result = verified_dependency.model_copy(
                    update={
                        "subtask_id": running.subtask_id,
                        "summary": (
                            "reused the approved implementation and passing test report "
                            "from the dependency; no patch or command was repeated"
                        ),
                        "metadata": {
                            **verified_dependency.metadata,
                            "status": "implemented_replay",
                            "replayed": True,
                            "verification_only": True,
                        },
                    }
                )
            else:
                result = executor_agent.run(running, all_subtasks, scenario)
            updated = running.model_copy(
                update={
                    "runtime_status": "executed",
                    "execution_result": result,
                    "evidence_refs": result.evidence_refs,
                }
            )
            event_emit(
                task_id=task_id,
                run_id=run_id,
                event_type="subtask_completed",
                actor_type="executor",
                actor_id=subtask.subtask_id,
                summary=f"executor finished: {result.summary}",
                payload_safe={
                    "subtask_id": subtask.subtask_id,
                    "status": result.metadata.get("status", "executed"),
                },
            )
            return {"subtasks": [updated], **tool_gateway.snapshot()}
        if running.assigned_role != "researcher":
            # 防御（PRODUCT-01）：不可执行角色立即记录失败特征（ReworkProgressGuard
            # 检测到连续无进展后由 Supervisor replan，不再盲重试至 rework_limit）。
            # 正常路径下 plan_validator 的 role_not_executable 已在规划期拦截。
            updated = running.model_copy(
                update={
                    "runtime_status": "rejected",
                    "rework_count": running.rework_count + 1,
                    "rework_signatures": running.rework_signatures
                    + [
                        failure_signature(
                            subtask.subtask_id,
                            subtask.assigned_role,
                            None,
                            ["unsupported_role"],
                        )
                    ],
                }
            )
            extra: dict[str, str] = {}
            if _guard.has_no_progress(updated.rework_signatures):
                # PRODUCT-01：连续无进展 → 停止盲重试，Supervisor replan
                extra = {"replan_reason": f"rework_no_progress: {subtask.subtask_id}"}
            event_emit(
                task_id=task_id,
                run_id=run_id,
                event_type="subtask_completed",
                actor_type=running.assigned_role,
                actor_id=subtask.subtask_id,
                summary=f"subtask rejected (unsupported role): {subtask.subtask_id}",
                payload_safe={"subtask_id": subtask.subtask_id, "status": "rejected"},
            )
            return {"subtasks": [updated], **extra, **tool_gateway.snapshot()}
        if llm_researcher is not None:
            result = llm_researcher.run(running, all_subtasks)
        else:
            result = researcher.run(running, all_subtasks, scenario)
        updated = running.model_copy(
            update={
                "runtime_status": "executed",
                "execution_result": result,
                "evidence_refs": result.evidence_refs,
            }
        )
        event_emit(
            task_id=task_id,
            run_id=run_id,
            event_type="subtask_completed",
            actor_type="researcher",
            actor_id=subtask.subtask_id,
            summary=f"research finished: {len(result.claims)} claims",
            payload_safe={
                "subtask_id": subtask.subtask_id,
                "claims": len(result.claims),
                "evidence": len(result.evidence_refs),
            },
        )
        # 回写工具调用/证据/幂等键（去重 reducer 合并，并行 exec 并发安全；快照在锁内生成）
        return {"subtasks": [updated], **tool_gateway.snapshot()}

    def review_all(state: TaskState) -> dict:
        """独立审查（004 十）：确定性检查 + 结构化评审；评审结果追加历史（不覆盖）。"""
        valid_ids = evidence_ids_of(state)
        if sandbox_context is not None:
            # M3-C：Executor 的 Claim 可引用 Artifact ID（diff/patch/test_report，十四.1）
            for artifact in sandbox_context.artifacts.load_all(state.task_id):
                valid_ids.add(artifact.artifact_id)
        active_subtasks = [item for item in state.subtasks if not item.superseded]
        dependency_ids = {
            dependency for item in active_subtasks for dependency in item.dependencies
        }
        updated_subtasks: list[SubtaskState] = []
        all_results: list[ReviewResult] = []
        for s in state.subtasks:
            if s.superseded or s.runtime_status != "executed":
                updated_subtasks.append(s)
                continue
            agent = registry.get(s.assigned_role)
            used_calls = role_used_tool_calls(state, s.assigned_role, s.subtask_id)
            issues = det_reviewer.check(s, valid_ids, agent.allowed_tools, used_calls)
            is_intermediate = s.subtask_id in dependency_ids
            if (
                not state.review_required or (is_intermediate and model_mode == "real")
            ) and not issues:
                # PRODUCT-01（纠偏令 021/024）：SIMPLE/TRIVIAL 快速路径跳过
                # Reviewer Gate（不调 LLM Reviewer）；确定性检查通过即 pass，
                # 确定性失败仍走 reject（保守，不放松安全）。
                claims = s.execution_result.claims if s.execution_result else []
                result = ReviewResult(
                    status=ReviewStatus.PASS,
                    summary="确定性验收通过；快速路径无需模型 Reviewer",
                    issues=[],
                    rework_targets=[],
                    accepted_claims=[c.claim_id for c in claims],
                    rejected_claims=[],
                )
            elif llm_reviewer is not None:
                # 005 15.3：确定性失败直接 reject，LLM 评审只在确定性通过后执行
                result = (
                    llm_reviewer.review(state, s, issues)
                    if not issues
                    else fake_reviewer.review(s, issues)
                )
            else:
                result = fake_reviewer.review(s, issues)
            if result.status in {ReviewStatus.REWORK, ReviewStatus.BLOCK}:
                if result.target_role == "assigned_role":
                    result.target_role = s.assigned_role
                updated = s.model_copy(
                    update={
                        "runtime_status": "rejected",
                        "rework_count": s.rework_count + 1,
                        "review_history": s.review_history + [result],
                        "rework_signatures": s.rework_signatures
                        + [
                            failure_signature(
                                s.subtask_id,
                                s.assigned_role,
                                s.execution_result,
                                [i.code for i in result.issues],
                                result.rework_targets,
                            )
                        ],
                    }
                )
            else:
                updated = s.model_copy(
                    update={
                        "runtime_status": "passed",
                        "review_history": s.review_history + [result],
                    }
                )
            updated_subtasks.append(updated)
            all_results.append(result)
        # 事件：review 结果（每个评审子任务一条）+ 返工开始
        from app.core.events import emit as event_emit

        executed_sids = [
            s.subtask_id
            for s in state.subtasks
            if not s.superseded and s.runtime_status == "executed"
        ]
        for sid, res in zip(executed_sids, all_results):
            event_emit(
                task_id=state.task_id,
                run_id=state.run_id,
                event_type=(
                    "review_passed"
                    if res.status in {ReviewStatus.PASS, ReviewStatus.PASS_WITH_NOTES}
                    else "review_blocked"
                    if res.status is ReviewStatus.BLOCK
                    else "review_rework"
                ),
                actor_type="reviewer",
                actor_id="reviewer",
                summary=f"{sid} {res.status.value}: {len(res.issues)} issues",
                payload_safe={
                    "subtask_id": sid,
                    "status": res.status.value,
                    "issues": len(res.issues),
                },
            )
        rejected_now = [
            s for s in updated_subtasks if not s.superseded and s.runtime_status == "rejected"
        ]
        if rejected_now:
            event_emit(
                task_id=state.task_id,
                run_id=state.run_id,
                event_type="rework_started",
                actor_type="supervisor",
                actor_id="supervisor",
                summary=f"rework started for: {[s.subtask_id for s in rejected_now]}",
                payload_safe={
                    "subtasks": [s.subtask_id for s in rejected_now],
                    "rework_count": max((s.rework_count for s in rejected_now), default=0),
                },
            )
        # PRODUCT-01（纠偏令 017）：连续返工无进展 → 停止盲重试，Supervisor replan
        no_progress_ids = _guard.no_progress_subtask_ids(rejected_now)
        replan_reason = None
        if no_progress_ids:
            replan_reason = f"rework_no_progress: {','.join(no_progress_ids)}"
            event_emit(
                task_id=state.task_id,
                run_id=state.run_id,
                event_type="replan_triggered",
                actor_type="supervisor",
                actor_id="supervisor",
                summary=f"no rework progress on {no_progress_ids}; supervisor replan",
                payload_safe={"subtask_ids": no_progress_ids, "reason": replan_reason},
            )
        elif rejected_now and any(
            s.rework_count > max_rework_for(state.complexity) for s in rejected_now
        ):
            # PRODUCT-01（020-B）：真实场景失败 signature 不稳定（模型输出每次变化），
            # guard 可能不触发；返工已达上限 → 停止盲重试，Supervisor replan 换方法。
            ids = [
                s.subtask_id
                for s in rejected_now
                if s.rework_count > max_rework_for(state.complexity)
            ]
            replan_reason = f"rework_limit_reached: {','.join(ids)}"
            event_emit(
                task_id=state.task_id,
                run_id=state.run_id,
                event_type="replan_triggered",
                actor_type="supervisor",
                actor_id="supervisor",
                summary=f"rework limit reached on {ids}; supervisor replan",
                payload_safe={"subtask_ids": ids, "reason": replan_reason},
            )
        return {
            "subtasks": updated_subtasks,
            "review_history": all_results,
            "rework_count": max(
                (s.rework_count for s in updated_subtasks if not s.superseded), default=0
            ),
            "replan_reason": replan_reason,
        }

    def route_after_review(state: TaskState) -> str:
        if state.replan_reason:
            return "plan"  # PRODUCT-01：Supervisor replan（换方法，停止盲重试）
        rejected = [
            s for s in state.subtasks if not s.superseded and s.runtime_status == "rejected"
        ]
        if rejected:
            # PRODUCT-01（020-B）：真实场景下失败 signature 常因模型输出变化而不稳定，
            # guard 可能不触发；返工已达上限 → 停止盲重试，优先 Supervisor replan
            # （换方法，replan 上限由 plan 节点兜底为 rework_limit_exceeded）。
            if any(s.rework_count > max_rework_for(state.complexity) for s in rejected):
                if state.replan_count < REPLAN_LIMIT:
                    return "plan"
                return "fail_rework_limit"
            return "dispatch"
        # 无 rejected：依赖链未完成的 pending 子任务继续派发（fan-in 后第二轮）
        by_id = {s.subtask_id: s for s in state.subtasks if not s.superseded}
        pending_ready = [
            s
            for s in state.subtasks
            if not s.superseded
            and s.runtime_status == "pending"
            and all(by_id[d].runtime_status == "passed" for d in s.dependencies)
        ]
        if pending_ready:
            return "dispatch"
        return "finalize"

    def fail_rework_limit(state: TaskState) -> dict:
        return {
            "current_status": "failed",
            "failure_code": "rework_limit_exceeded",
            "final_result": (
                "Reviewer 连续发现核心验收未通过。系统已完成 "
                f"{max_rework_for(state.complexity)} 次定向返工，仍未满足条件，"
                "已停止继续消耗模型预算。"
            ),
            "failure_details": {
                "failed_stage": "review",
                "agent": "reviewer",
                "failure_code": "rework_limit_exceeded",
                "root_cause": "core acceptance criteria remain unsatisfied",
                "recovery_attempt": "targeted local rework",
                "final_decision": "stopped before blind retry",
                "actions": ["retry_failed_step", "replan", "view_details"],
            },
        }

    def finalize(state: TaskState) -> dict:
        """最终汇总（004 十四）：全部子任务通过 + 无未处理审批 + 预算未超 + 无不可恢复错误。"""
        active = [s for s in state.subtasks if not s.superseded]
        all_passed = all(s.runtime_status == "passed" for s in active)
        has_pending_approval = any(
            (a.get("status") if isinstance(a, dict) else a.status) == "pending"
            for a in state.approvals
        )
        if not all_passed or has_pending_approval:
            return {
                "current_status": "failed",
                "failure_code": "finalize_conditions_not_met",
                "final_result": (
                    "finalize 条件未满足: "
                    f"all_passed={all_passed}, pending_approval={has_pending_approval}"
                ),
            }
        completion = _completion.validate(state, TaskShape(state.task_shape))
        if not completion.complete:
            return {
                "current_status": "failed",
                "failure_code": "completion_invalid",
                "final_result": (
                    "任务执行链结束，但产品完成条件未满足：" + ", ".join(completion.reasons)
                ),
                "failure_details": {
                    "failed_stage": "completion_validation",
                    "agent": "supervisor",
                    "failure_code": "completion_invalid",
                    "root_cause": completion.reasons,
                    "recovery_attempt": "none",
                    "final_decision": "not marked completed",
                    "actions": ["retry_failed_step", "replan", "view_details"],
                },
            }
        evidence_index = list(dict.fromkeys(eid for s in active for eid in s.evidence_refs))
        unverified = list(
            dict.fromkeys(
                item
                for s in active
                if s.execution_result
                for item in s.execution_result.unverified_items
            )
        )
        is_real_run = state.model_mode == "real"
        report = FinalReport(
            summary=(
                _direct_response(state.user_goal)
                if not active and state.task_shape == TaskShape.DIRECT_RESPONSE.value
                else "\n\n".join(
                    f"### {s.title}\n{s.execution_result.summary}\n"
                    + "\n".join(f"- {claim.text}" for claim in s.execution_result.claims)
                    for s in active
                    if s.execution_result is not None
                )
                if is_real_run
                else f"任务 '{state.user_goal}' 完成：{len(active)} 个子任务全部通过"
            ),
            decision="accept",
            evidence_index=evidence_index,
            limitations=(
                []
                if is_real_run
                else ["M2 使用 DeterministicFakeModel 与 Fixture 数据，未接入真实模型/网络"]
            ),
            unverified_items=unverified,
            execution_summary={
                "subtask_count": len(active),
                "rework_count": state.rework_count,
                "tool_call_count": len(state.tool_calls),
                "tokens": state.budget_usage.get("tokens", 0.0),
            },
        )
        if llm_supervisor is not None and not is_real_run:
            # 005 15.4：模型仅参与语言组织；失败回退确定性汇总
            composed = llm_supervisor.compose_summary(state)
            # REAL 验收以运行时事实为最终依据。真实模型仍参与 Supervisor 调用，
            # 但不得用语言生成结果覆盖补丁、测试、审批与 Reviewer 的确定性状态。
            if composed and not is_real_run:
                report.summary = composed.get("summary", report.summary)
                report.limitations.extend(composed.get("limitations", []) or [])
                if composed.get("downgrade_note"):
                    report.limitations.append(f"降级说明: {composed['downgrade_note']}")
        return {
            "final_result": report.model_dump_json(indent=2, ensure_ascii=False),
            "final_evidence": state.evidence,
            "current_status": "completed",
        }

    # ---------- 图装配 ----------
    graph = StateGraph(TaskState)
    graph.add_node("ingest", ingest)
    graph.add_node("clarify", clarify)
    graph.add_node("plan", plan)
    graph.add_node("dispatch", dispatch)
    graph.add_node("exec_subtask", exec_subtask)  # type: ignore[type-var]  # Send 目标输入为 payload dict
    graph.add_node("review_all", review_all)
    graph.add_node("finalize", finalize)
    graph.add_node("fail_rework_limit", fail_rework_limit)

    graph.add_edge(START, "ingest")
    graph.add_conditional_edges(
        "ingest",
        route_ingest,
        {"clarify": "clarify", "plan": "plan", "end": END},
    )
    graph.add_edge("clarify", "plan")
    graph.add_conditional_edges("plan", route_plan, {"dispatch": "dispatch", "end": END})
    # dispatch → Send fan-out（exec_subtask 并行）→ fan-in（全部完成后沿静态边继续 review_all）
    graph.add_conditional_edges(
        "dispatch",
        route_dispatch,
        ["exec_subtask", "review_all"],
    )
    graph.add_edge("exec_subtask", "review_all")
    graph.add_conditional_edges(
        "review_all",
        route_after_review,
        {
            "finalize": "finalize",
            "dispatch": "dispatch",
            "fail_rework_limit": "fail_rework_limit",
            "plan": "plan",  # PRODUCT-01：无进展 → Supervisor replan
        },
    )
    graph.add_edge("finalize", END)
    graph.add_edge("fail_rework_limit", END)
    return graph
