from __future__ import annotations

import json

from app.agents.llm_agents import LLMPlanner, LLMReviewer
from app.core.config import AppSettings, ModelProviderSettings, ModelRouteSettings
from app.core.context_builder import ContextBuilder
from app.core.registry import default_registry
from app.core.schemas import Claim, ExecutionResult
from app.core.state import SubtaskState, TaskState
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
    assert "sandbox_REAL01" in plan.subtasks[0].input_refs
    assert len(gateway.requests) == 2
    assert "Deterministic tool policy" in gateway.requests[0].messages[1]["content"]
    assert "Return exactly one JSON object" in gateway.requests[0].messages[0]["content"]
    assert "exactly two subtasks" in gateway.requests[1].messages[-1]["content"]


def test_real_planner_repairs_researcher_capability_mismatch() -> None:
    invalid_researcher = _subtask("research", "researcher", [])
    invalid_researcher["objective"] = "运行 pytest 并记录用户权限决策"
    invalid_researcher["acceptance_criteria"] = ["pytest output", "用户决策"]
    valid_researcher = _subtask("research", "researcher", [])
    valid_researcher["objective"] = "read source and identify the failing assertion"
    executor = _subtask("execute", "executor", ["research"])
    executor["acceptance_criteria"] = ["pytest passes"]
    gateway = SequenceGateway(
        [_plan([invalid_researcher, executor]), _plan([valid_researcher, executor])]
    )
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
        user_goal="sandbox_REAL01：修复失败测试",
        token_budget=10000,
        cost_budget=1,
    )

    plan = planner.make_plan(state, ["researcher", "executor"])

    assert "pytest" not in plan.subtasks[0].objective
    assert len(gateway.requests) == 2
    assert "cannot run pytest" in gateway.requests[1].messages[-1]["content"]


def test_reviewer_does_not_reject_verified_evidence_only_for_prompt_truncation() -> None:
    gateway = SequenceGateway(
        [
            {
                "verdict": "reject",
                "issues": [
                    {
                        "code": "incomplete_evidence",
                        "message": "证据内容被截断，未提供完整内容",
                    }
                ],
                "rework_targets": ["research"],
                "accepted_claims": [],
                "rejected_claims": ["c1"],
            }
        ]
    )
    settings = AppSettings(
        model=ModelProviderSettings(default_model="deepseek-v4-flash"),
        routing=ModelRouteSettings(
            role_defaults={"reviewer": "deepseek-v4-flash"},
            allowed_models=["deepseek-v4-flash"],
        ),
    )
    reviewer = LLMReviewer(
        gateway,  # type: ignore[arg-type]
        ModelRouter(settings.routing),
        ContextBuilder(settings),
        settings,
    )
    result = ExecutionResult(
        subtask_id="research",
        summary="verified",
        claims=[Claim(claim_id="c1", text="root cause", evidence_ids=["e1"])],
        evidence_refs=["e1"],
        ts="",
        metadata={
            "evidence_contract": "verified_local_files",
            "local_evidence": [{"path": "src/main.py", "content": "return False"}],
        },
    )
    subtask = SubtaskState(
        subtask_id="research",
        title="research",
        objective="identify root cause",
        dependencies=[],
        assigned_role="researcher",
        input_refs=["sandbox_REAL01"],
        expected_output="evidence",
        acceptance_criteria=["cite evidence"],
        required_tools=["local_read_text"],
        token_budget=1000,
        tool_call_budget=2,
        execution_result=result,
    )
    state = TaskState(
        task_id="task",
        run_id="run",
        user_goal="sandbox_REAL01",
        token_budget=10000,
        cost_budget=1,
        subtasks=[subtask],
    )

    review = reviewer.review(state, subtask, [])

    assert review.verdict == "pass"
    assert review.accepted_claims == ["c1"]
