"""LangGraph 最小图（M1 单节点）+ checkpoint 版本校验。"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.core.state import CHECKPOINT_VERSION, TaskState, TaskStatus
from app.gateway.model_gateway import ModelGateway


def _validate_checkpoint(state: TaskState) -> None:
    """R18：恢复前校验 checkpoint schema 版本。"""
    if state.checkpoint_version != CHECKPOINT_VERSION:
        raise RuntimeError(
            f"checkpoint version mismatch: {state.checkpoint_version} != {CHECKPOINT_VERSION}"
        )


def build_graph(model_gateway: ModelGateway) -> StateGraph:
    """M1 单节点图：agent 节点经 Model Gateway 回答（预算由网关强制）。"""

    def run_agent(state: TaskState) -> dict:
        _validate_checkpoint(state)
        resp = model_gateway.chat([{"role": "user", "content": state.user_goal}], max_tokens=256)
        return {"current_status": TaskStatus.COMPLETED, "final_result": resp.text}

    graph = StateGraph(TaskState)
    graph.add_node("agent", run_agent)
    graph.add_edge(START, "agent")
    graph.add_edge("agent", END)
    return graph
