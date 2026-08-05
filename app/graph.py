"""LangGraph 图（M1）+ pause 节点（003-A 二）。

- agent 节点：工具步骤（FixtureRepositoryLookupTool）+ 模型步骤（Model Gateway），
  并把 budget_usage / tool_calls / evidence / idempotency_keys 回写状态（跨进程持久化）。
- pause 节点：pause_after="agent" 时插入，interrupt() 在节点边界暂停；
  恢复经 Command(resume=ResumePayload)（禁止 resume=None，见 docs/adr/0001）。
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.core.resume import ResumePayload
from app.core.state import CHECKPOINT_VERSION, TaskState
from app.gateway.model_gateway import ModelGateway
from app.gateway.tool_gateway import ToolGateway


def _validate_checkpoint(state: TaskState) -> None:
    """R18：恢复前校验 checkpoint schema 版本。"""
    if state.checkpoint_version != CHECKPOINT_VERSION:
        raise RuntimeError(
            f"checkpoint version mismatch: {state.checkpoint_version} != {CHECKPOINT_VERSION}"
        )


def build_graph(
    model_gateway: ModelGateway,
    tool_gateway: ToolGateway,
    pause_after: str | None = None,
) -> StateGraph:
    """M1 图：START → agent → [pause] → END。pause_after 仅支持 "agent"。"""

    def run_agent(state: TaskState) -> dict:
        _validate_checkpoint(state)
        # 工具步骤（只读 fixture；恢复时幂等键命中则 skipped，不重复执行）
        tool_gateway.invoke("fixture_repo_lookup", {"repo_name": "langgraph"})
        # 模型步骤（预算由 Model Gateway 强制）
        resp = model_gateway.chat([{"role": "user", "content": state.user_goal}], max_tokens=256)
        return {
            # 无 pause 时直接完成；有 pause 时由 pause 节点在恢复后置为 completed
            "current_status": "executing" if pause_after == "agent" else "completed",
            "final_result": resp.text,
            "budget_usage": model_gateway.budget.usage,
            "tool_calls": tool_gateway.tool_calls,
            "evidence": tool_gateway.evidence,
            "idempotency_keys": sorted(tool_gateway.seen_keys),
        }

    def maybe_pause(state: TaskState) -> dict:
        # 首次执行时 interrupt() 抛出 GraphInterrupt（节点边界暂停，checkpoint 已保存）；
        # 恢复时 interrupt() 返回 ResumePayload，节点继续并完成。
        _ = interrupt(ResumePayload(action="continue"))
        return {"current_status": "completed"}

    graph = StateGraph(TaskState)
    graph.add_node("agent", run_agent)
    graph.add_edge(START, "agent")
    if pause_after == "agent":
        graph.add_node("pause", maybe_pause)
        graph.add_edge("agent", "pause")
        graph.add_edge("pause", END)
    else:
        graph.add_edge("agent", END)
    return graph
