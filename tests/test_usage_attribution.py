from __future__ import annotations

import inspect
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

import app.api.server as server
from app.agents.llm_agents import LLMResearcher
from app.core.budget import BudgetController
from app.core.config import AppSettings, ModelProviderSettings, ModelRouteSettings
from app.core.context_builder import ContextBuilder
from app.core.evidence import EvidenceWriter
from app.core.state import SubtaskState
from app.gateway.audit import AuditLog
from app.gateway.contracts import ModelRequest, ModelResponse, UsageEstimate
from app.gateway.model_gateway import ModelGateway
from app.gateway.router import ModelRouter
from app.gateway.structured_gen import generate_structured
from app.gateway.tool_gateway import ToolGateway
from app.runner import run_task
from app.usage.models import CostSource, NormalizedModelUsage, UsageSource
from app.usage.reconciler import UsageReconciler
from app.usage.store import UsageStore


def _usage(
    call_id: str,
    *,
    task_id: str = "task-1",
    run_id: str | None = "run-1",
    role: str = "planner",
    provider: str = "DeepSeek Official",
    model: str = "deepseek-v4-flash",
    tokens: int = 100,
    source: UsageSource = UsageSource.REPORTED,
    scope: str = "user_task",
) -> NormalizedModelUsage:
    return NormalizedModelUsage(
        usage_id=f"usage-{call_id}",
        scope=scope,
        task_id=task_id,
        run_id=run_id,
        call_id=call_id,
        role=role,
        agent_id=role,
        provider_id=provider,
        provider_name=provider,
        model_id=model,
        input_tokens=tokens - 10,
        output_tokens=10,
        total_tokens=tokens,
        usage_source=source,
        latency_ms=10,
        cost_source=CostSource.UNAVAILABLE,
    )


def _five_call_store(tmp_path: Path) -> UsageStore:
    store = UsageStore(tmp_path)
    for index, (role, tokens) in enumerate(
        zip(
            ["supervisor", "planner", "researcher", "executor", "reviewer"],
            [100, 200, 300, 400, 500],
            strict=True,
        ),
        start=1,
    ):
        store.record(_usage(f"c{index}", role=role, tokens=tokens))
    return store


def test_usage_attr01_one_task_five_calls(tmp_path: Path) -> None:
    summary = _five_call_store(tmp_path).summary(
        run_id="run-1", days=None, scope="user_task"
    )
    assert summary["requests"] == 5


def test_usage_attr01_structured_repair_is_a_distinct_call(tmp_path: Path) -> None:
    class RepairProvider:
        provider_name = "DeepSeek Official"

        def __init__(self) -> None:
            self.call_count = 0

        def estimate_usage(self, _request):
            return UsageEstimate(estimated_input_tokens=10, estimated_max_output_tokens=10)

        def generate(self, request):
            self.call_count += 1
            return ModelResponse(
                request_id=request.request_id,
                provider=self.provider_name,
                model=request.model,
                raw_text="invalid" if self.call_count == 1 else '{"ok":true}',
                input_tokens=10,
                output_tokens=2,
                total_tokens=12,
                usage_source="REPORTED",
                latency_ms=1,
            )

    store = UsageStore(tmp_path)
    gateway = ModelGateway(
        provider=RepairProvider(),
        budget=BudgetController(1000, 1.0),
        audit=AuditLog(tmp_path / "repair-audit.jsonl"),
        task_id="task-1",
        run_id="run-1",
        usage_store=store,
    )
    result = generate_structured(
        gateway,
        ModelRequest(
            request_id="repair-call",
            task_id="task-1",
            run_id="run-1",
            agent_id="planner",
            role_type="planner",
            model="deepseek-v4-flash",
            messages=[{"role": "user", "content": "return JSON"}],
        ),
        {"ok": {"type": "bool"}},
        AppSettings(max_output_repair_attempts=1),
    )
    with sqlite3.connect(store.path) as conn:
        call_ids = [row[0] for row in conn.execute("SELECT call_id FROM model_usage")]
    assert result == {"ok": True}
    assert len(call_ids) == len(set(call_ids)) == 2


def test_usage_attr02_five_call_token_sum(tmp_path: Path) -> None:
    summary = _five_call_store(tmp_path).summary(
        run_id="run-1", days=None, scope="user_task"
    )
    assert summary["total_tokens"] == 1500


def test_usage_attr03_multiple_roles_keep_parent_task(tmp_path: Path) -> None:
    summary = _five_call_store(tmp_path).summary(
        task_id="task-1", days=None, scope="user_task"
    )
    assert {item["name"] for item in summary["by_agent"]} == {
        "supervisor",
        "planner",
        "researcher",
        "executor",
        "reviewer",
    }


def test_usage_attr04_researcher_subtask_keeps_parent_ids(tmp_path: Path) -> None:
    class CaptureGateway:
        def __init__(self) -> None:
            self.requests = []

        def generate(self, request, **_kwargs):
            self.requests.append(request.model_copy(deep=True))
            raw = (
                '{"round":1,"done":true,"tool_calls":[]}'
                if len(self.requests) == 1
                else '{"summary":"ok","claims":[],"evidence_refs":[],'
                '"unverified_items":[],"confidence":1.0}'
            )
            return ModelResponse(
                request_id=request.request_id,
                provider="test",
                model=request.model,
                raw_text=raw,
            )

    settings = AppSettings(
        model=ModelProviderSettings(default_model="deepseek-v4-flash"),
        routing=ModelRouteSettings(
            role_defaults={"researcher": "deepseek-v4-flash"},
            allowed_models=["deepseek-v4-flash"],
        ),
    )
    gateway = CaptureGateway()
    audit = AuditLog(tmp_path / "audit.jsonl")
    tools = ToolGateway(
        audit=audit,
        task_id="parent-task",
        run_id="parent-run",
        evidence_writer=EvidenceWriter(tmp_path / "runtime", "parent-task"),
    )
    researcher = LLMResearcher(
        gateway,  # type: ignore[arg-type]
        ModelRouter(settings.routing),
        ContextBuilder(settings),
        settings,
        tools,
    )
    subtask = SubtaskState(
        subtask_id="child-subtask",
        title="research",
        objective="inspect",
        assigned_role="researcher",
        expected_output="report",
        acceptance_criteria=["complete"],
        token_budget=1000,
        tool_call_budget=2,
    )

    researcher.run(subtask, [subtask])

    assert {(item.task_id, item.run_id) for item in gateway.requests} == {
        ("parent-task", "parent-run")
    }


def test_usage_attr05_diagnostic_isolated_from_user_task(tmp_path: Path) -> None:
    store = UsageStore(tmp_path)
    store.record(_usage("user"))
    store.record(_usage("diag", tokens=900, scope="diagnostic"))
    summary = store.summary(run_id="run-1", days=None, scope="user_task")
    assert (summary["requests"], summary["total_tokens"]) == (1, 100)


def test_usage_attr06_cached_input_not_double_counted() -> None:
    normalized = UsageReconciler.deepseek_usage(
        {
            "prompt_tokens": 659,
            "completion_tokens": 118,
            "total_tokens": 777,
            "prompt_cache_hit_tokens": 640,
        }
    )
    assert normalized["total_tokens"] == 777
    assert normalized["cached_input_tokens"] == 640


def test_usage_attr07_by_agent_sum_matches_task(tmp_path: Path) -> None:
    summary = _five_call_store(tmp_path).summary(run_id="run-1", days=None)
    assert sum(item["tokens"] for item in summary["by_agent"]) == summary["total_tokens"]
    assert sum(item["requests"] for item in summary["by_agent"]) == summary["requests"]


def test_usage_attr08_by_model_sum_matches_task(tmp_path: Path) -> None:
    store = _five_call_store(tmp_path)
    store.record(_usage("m2", model="other-model", tokens=25))
    summary = store.summary(run_id="run-1", days=None)
    assert sum(item["tokens"] for item in summary["by_model"]) == summary["total_tokens"]
    assert sum(item["requests"] for item in summary["by_model"]) == summary["requests"]


def test_usage_attr09_by_provider_sum_matches_task(tmp_path: Path) -> None:
    store = _five_call_store(tmp_path)
    store.record(_usage("p2", provider="Other Provider", tokens=25))
    summary = store.summary(run_id="run-1", days=None)
    assert sum(item["tokens"] for item in summary["by_provider"]) == summary["total_tokens"]
    assert sum(item["requests"] for item in summary["by_provider"]) == summary["requests"]


def test_usage_attr10_timeline_calls_equal_requests(tmp_path: Path) -> None:
    summary = _five_call_store(tmp_path).summary(run_id="run-1", days=None)
    assert len(summary["timeline"]) == summary["requests"]


def test_usage_attr11_current_run_filter_and_task_api_ids(
    tmp_path: Path, monkeypatch
) -> None:
    report = run_task("github_compare_team", 10_000, 1.0, data_dir=tmp_path)
    store = UsageStore(tmp_path)
    store.record(_usage("current", task_id=report.task_id, run_id=report.run_id, tokens=120))
    store.record(_usage("old", task_id=report.task_id, run_id="old-run", tokens=880))
    monkeypatch.setenv("AI_TEAM_OS_DATA_DIR", str(tmp_path))
    server._settings_cache = None
    with TestClient(server.app) as client:
        payload = client.get(f"/tasks/{report.run_id}/usage").json()
    assert payload["task_id"] == report.task_id
    assert payload["run_id"] == report.run_id
    assert (payload["requests"], payload["total_tokens"]) == (1, 120)


def test_usage_attr12_mixed_sources_not_reported(tmp_path: Path) -> None:
    store = UsageStore(tmp_path)
    store.record(_usage("reported", source=UsageSource.REPORTED))
    store.record(_usage("estimated", source=UsageSource.ESTIMATED))
    summary = store.summary(run_id="run-1", days=None)
    assert summary["usage_source"] == "ESTIMATED"


def test_usage_attr13_legacy_row_without_run_id_is_safe(tmp_path: Path) -> None:
    store = UsageStore(tmp_path)
    store.record(_usage("legacy", task_id="legacy-subtask", run_id=None))
    with sqlite3.connect(store.path) as conn:
        conn.execute("UPDATE model_usage SET scope='user_task' WHERE call_id='legacy'")
    summary = store.summary(task_id="legacy-subtask", days=None, scope="user_task")
    assert (summary["requests"], summary["total_tokens"]) == (1, 100)


def test_usage_attr14_graph_dict_state_boundary_regression() -> None:
    from app.graph import build_graph

    source = inspect.getsource(build_graph)
    researcher_branch = source.split("if llm_researcher is not None:", 1)[1].split(
        "else:", 1
    )[0]
    assert "state.task_id" not in researcher_branch
    assert "state.run_id" not in researcher_branch
