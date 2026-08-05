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
    LLMPlanner,
    LLMResearcher,
    LLMReviewer,
    LLMSupervisorDecision,
)
from app.agents.planner import make_plan
from app.agents.researcher import FakeResearcher
from app.agents.reviewer import (
    MAX_REWORK,
    DeterministicReviewer,
    FakeReviewer,
    evidence_ids_of,
    role_used_tool_calls,
)
from app.core.config import AppSettings
from app.core.context_builder import ContextBuilder
from app.core.plan_validator import PlanValidationError, validate_plan
from app.core.registry import AgentRegistry, default_registry
from app.core.schemas import (
    ClarificationPayload,
    ClarificationRecord,
    FinalReport,
    ReviewResult,
)
from app.core.state import CHECKPOINT_VERSION, SubtaskState, TaskState
from app.gateway.contracts import ProviderError
from app.gateway.model_gateway import ModelGateway
from app.gateway.router import ModelRouter
from app.gateway.tool_gateway import ToolGateway

MAX_CLARIFICATION_ROUNDS = 3  # 集中配置（004 十三）
PLAN_RETRY_LIMIT = 2  # 集中配置（004 六）


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    """确定性模糊判定（004 十三）：超短/无结构目标需要澄清。"""
    stripped = goal.strip()
    return len(stripped) < 8 or stripped in {"帮我做个东西", "vague_goal", "做点东西"}


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
    settings = settings or AppSettings()
    router = router or ModelRouter(settings.routing)
    context = context or ContextBuilder(settings)
    executor_agent = (
        DeterministicFakeExecutor(sandbox_context) if sandbox_context is not None else None
    )
    llm_planner = (
        LLMPlanner(model_gateway, router, context, settings) if model_mode == "real" else None
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
        last_error: PlanValidationError | ProviderError | None = None
        for _attempt in range(PLAN_RETRY_LIMIT + 1):
            try:
                if llm_planner is not None:
                    plan_obj = llm_planner.make_plan(
                        state, [a.agent_id for a in registry.all() if a.enabled]
                    )
                else:
                    plan_obj = make_plan(
                        plan_scenario, goal_text, task_token_budget=state.token_budget
                    )
                validate_plan(plan_obj, registry, state.token_budget)
                subtasks = [SubtaskState(**s.model_dump()) for s in plan_obj.subtasks]
                return {
                    "plan": plan_obj.model_dump(),
                    "subtasks": subtasks,
                    "selected_agents": {s.subtask_id: s.assigned_role for s in plan_obj.subtasks},
                    "current_status": "planning",
                }
            except (PlanValidationError, ProviderError) as exc:  # noqa: PERF203
                last_error = exc
        # 超过重试上限：进入 failed/planning_invalid，不得绕过 Schema 继续（004 六 / 005 15.1）
        return {
            "current_status": "failed",
            "failure_code": "planning_invalid",
            "final_result": f"plan invalid after {PLAN_RETRY_LIMIT + 1} attempts: {last_error}",
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
            if s.runtime_status not in ("pending", "rejected"):
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
        running = subtask.model_copy(update={"runtime_status": "running"})
        if running.assigned_role == "executor":
            # 007 十二/十三：Executor 工作流（审批 interrupt 在此节点内）
            if executor_agent is None:
                updated = running.model_copy(
                    update={
                        "runtime_status": "rejected",
                        "rework_count": running.rework_count + 1,
                    }
                )
                return {"subtasks": [updated], **tool_gateway.snapshot()}
            result = executor_agent.run(running, all_subtasks, scenario)
            updated = running.model_copy(
                update={
                    "runtime_status": "executed",
                    "execution_result": result,
                    "evidence_refs": result.evidence_refs,
                }
            )
            return {"subtasks": [updated], **tool_gateway.snapshot()}
        if running.assigned_role != "researcher":
            # 防御：M2 不支持的执行角色模拟 reject 语义（递增 rework_count），
            # 经 route_after_review 的返工上限收敛为 failed/rework_limit_exceeded
            updated = running.model_copy(
                update={
                    "runtime_status": "rejected",
                    "rework_count": running.rework_count + 1,
                }
            )
            return {"subtasks": [updated], **tool_gateway.snapshot()}
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
        # 回写工具调用/证据/幂等键（去重 reducer 合并，并行 exec 并发安全；快照在锁内生成）
        return {"subtasks": [updated], **tool_gateway.snapshot()}

    def review_all(state: TaskState) -> dict:
        """独立审查（004 十）：确定性检查 + 结构化评审；评审结果追加历史（不覆盖）。"""
        valid_ids = evidence_ids_of(state)
        updated_subtasks: list[SubtaskState] = []
        all_results: list[ReviewResult] = []
        for s in state.subtasks:
            if s.runtime_status != "executed":
                updated_subtasks.append(s)
                continue
            agent = registry.get(s.assigned_role)
            used_calls = role_used_tool_calls(state, s.assigned_role, s.subtask_id)
            issues = det_reviewer.check(s, valid_ids, agent.allowed_tools, used_calls)
            if llm_reviewer is not None:
                # 005 15.3：确定性失败直接 reject，LLM 评审只在确定性通过后执行
                result = (
                    llm_reviewer.review(state, s, issues)
                    if not issues
                    else fake_reviewer.review(s, issues)
                )
            else:
                result = fake_reviewer.review(s, issues)
            if result.verdict == "reject":
                updated = s.model_copy(
                    update={
                        "runtime_status": "rejected",
                        "rework_count": s.rework_count + 1,
                        "review_history": s.review_history + [result],
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
        return {
            "subtasks": updated_subtasks,
            "review_history": all_results,
            "rework_count": max((s.rework_count for s in updated_subtasks), default=0),
        }

    def route_after_review(state: TaskState) -> str:
        rejected = [s for s in state.subtasks if s.runtime_status == "rejected"]
        if rejected:
            if any(s.rework_count > MAX_REWORK for s in rejected):
                return "fail_rework_limit"
            return "dispatch"
        # 无 rejected：依赖链未完成的 pending 子任务继续派发（fan-in 后第二轮）
        by_id = {s.subtask_id: s for s in state.subtasks}
        pending_ready = [
            s
            for s in state.subtasks
            if s.runtime_status == "pending"
            and all(by_id[d].runtime_status == "passed" for d in s.dependencies)
        ]
        if pending_ready:
            return "dispatch"
        return "finalize"

    def fail_rework_limit(state: TaskState) -> dict:
        return {
            "current_status": "failed",
            "failure_code": "rework_limit_exceeded",
            "final_result": f"返工次数超过上限 {MAX_REWORK}，停止",
        }

    def finalize(state: TaskState) -> dict:
        """最终汇总（004 十四）：全部子任务通过 + 无未处理审批 + 预算未超 + 无不可恢复错误。"""
        all_passed = all(s.runtime_status == "passed" for s in state.subtasks)
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
        evidence_index = list(dict.fromkeys(eid for s in state.subtasks for eid in s.evidence_refs))
        unverified = list(
            dict.fromkeys(
                item
                for s in state.subtasks
                if s.execution_result
                for item in s.execution_result.unverified_items
            )
        )
        report = FinalReport(
            summary=f"任务 '{state.user_goal}' 完成：{len(state.subtasks)} 个子任务全部通过",
            decision="accept",
            evidence_index=evidence_index,
            limitations=["M2 使用 DeterministicFakeModel 与 Fixture 数据，未接入真实模型/网络"],
            unverified_items=unverified,
            execution_summary={
                "subtask_count": len(state.subtasks),
                "rework_count": state.rework_count,
                "tool_call_count": len(state.tool_calls),
                "tokens": state.budget_usage.get("tokens", 0.0),
            },
        )
        if llm_supervisor is not None:
            # 005 15.4：模型仅参与语言组织；失败回退确定性汇总
            composed = llm_supervisor.compose_summary(state)
            if composed:
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
        {"finalize": "finalize", "dispatch": "dispatch", "fail_rework_limit": "fail_rework_limit"},
    )
    graph.add_edge("finalize", END)
    graph.add_edge("fail_rework_limit", END)
    return graph
