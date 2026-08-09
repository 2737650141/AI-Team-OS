from __future__ import annotations

import json

from app.agents.llm_agents import LLMPlanner
from app.core.config import AppSettings, ModelProviderSettings, ModelRouteSettings
from app.core.context_builder import ContextBuilder
from app.core.registry import default_registry
from app.core.state import TaskState
from app.gateway.contracts import ModelResponse
from app.gateway.router import ModelRouter


class SequenceGateway:
    def __init__(self, outputs: list[dict]) -> None:
        self.outputs = outputs
        self.requests = []

    def generate(self, request, **_kwargs) -> ModelResponse:
        self.requests.append(request.model_copy(deep=True))
        output = self.outputs.pop(0)
        return ModelResponse(
            request_id=request.request_id,
            provider="test-real",
            model=request.model,
            raw_text=json.dumps(output),
        )


def _plan(subtasks: list[dict]) -> dict:
    return {"goal": "sandbox_REAL01", "subtasks": subtasks}


def _subtask(subtask_id: str, role: str, dependencies: list[str]) -> dict:
    tools = (
        ["local_read_text"]
        if role == "researcher"
        else ["sandbox_apply_patch"]
        if role == "executor"
        else []
    )
    return {
        "subtask_id": subtask_id,
        "title": subtask_id,
        "objective": "inspect" if role == "researcher" else "patch",
        "dependencies": dependencies,
        "assigned_role": role,
        "input_refs": [],
        "expected_output": "evidence" if role == "researcher" else "diff",
        "acceptance_criteria": ["verified"],
        "required_tools": tools,
        "token_budget": 1000,
        "tool_call_budget": 2,
    }


def test_real_planner_repairs_explicit_two_step_constraint() -> None:
    researcher = _subtask("research", "researcher", [])
    executor = _subtask("execute", "executor", ["research"])
    extra = _subtask("extra", "reviewer", ["execute"])
    gateway = SequenceGateway([_plan([researcher, executor, extra]), _plan([researcher, executor])])
    settings = AppSettings(
        model=ModelProviderSettings(default_model="deepseek-v4-flash"),
        routing=ModelRouteSettings(
            role_defaults={"planner": "deepseek-v4-flash"},
            allowed_models=["deepseek-v4-flash"],
        ),
        max_output_repair_attempts=1,
    )
    planner = LLMPlanner(
        gateway,  # type: ignore[arg-type]
        ModelRouter(settings.routing),
        ContextBuilder(settings),
        settings,
        default_registry(),
    )
    state = TaskState(
        task_id="task",
        run_id="run",
        user_goal="sandbox_REAL01：Planner 必须创建两个子任务",
        token_budget=10000,
        cost_budget=1,
    )

    plan = planner.make_plan(state, ["researcher", "executor"])

    assert [item.assigned_role for item in plan.subtasks] == ["researcher", "executor"]
    assert len(gateway.requests) == 2
    assert "Deterministic tool policy" in gateway.requests[0].messages[1]["content"]
    assert "Return exactly one JSON object" in gateway.requests[0].messages[0]["content"]
    assert "exactly two subtasks" in gateway.requests[1].messages[-1]["content"]
