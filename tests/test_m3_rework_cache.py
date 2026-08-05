"""004 4.x：M2 限制修复——幂等缓存复用（cached_success_result）测试（4.3 八项）。"""

from __future__ import annotations

from pathlib import Path

from app.agents.researcher import FakeResearcher
from app.agents.reviewer import DeterministicReviewer
from app.core.state import SubtaskState
from app.gateway.audit import AuditLog
from app.gateway.tool_gateway import ToolGateway
from app.runner import run_task, trace_task
from app.tools.fixture_repo import FixtureRepositoryLookupTool
from tests.conftest import FIXTURE_REPOS


def _gateway(tmp_path: Path, call_counter: list[int] | None = None) -> ToolGateway:
    gw = ToolGateway(audit=AuditLog(tmp_path / "audit.jsonl"), task_id="t-cache")

    class CountingLookup(FixtureRepositoryLookupTool):
        def handler(self, repo_name: str) -> dict:  # type: ignore[override]
            if call_counter is not None:
                call_counter[0] += 1
            return super().handler(repo_name)

    gw.register(CountingLookup(FIXTURE_REPOS).spec())
    return gw


def _subtask(sid: str = "s1") -> SubtaskState:
    return SubtaskState(
        subtask_id=sid,
        title="repo",
        objective="o",
        dependencies=[],
        assigned_role="researcher",
        input_refs=["fixture_repo_lookup:langgraph"],
        expected_output="r",
        acceptance_criteria=["a"],
        required_tools=["fixture_repo_lookup"],
        token_budget=1000,
        tool_call_budget=4,
    )


def test_cached_same_args_returns_full_result(tmp_path: Path) -> None:
    """4.3-1：相同参数命中缓存并返回完整结果。"""
    gw = _gateway(tmp_path)
    r1 = gw.invoke("fixture_repo_lookup", {"repo_name": "langgraph"})
    r2 = gw.invoke("fixture_repo_lookup", {"repo_name": "langgraph"})
    assert r1.ok and r2.ok
    assert r2.status == "cached_success_result"
    assert r2.data == r1.data  # 完整结构化结果复用


def test_handler_not_re_executed(tmp_path: Path) -> None:
    """4.3-2：handler 不重复执行（幂等命中时）。"""
    counter = [0]
    gw = _gateway(tmp_path, call_counter=counter)
    gw.invoke("fixture_repo_lookup", {"repo_name": "langgraph"})
    gw.invoke("fixture_repo_lookup", {"repo_name": "langgraph"})
    assert counter[0] == 1


def test_evidence_id_reused(tmp_path: Path) -> None:
    """4.3-3：Evidence ID 可复用（缓存命中返回原 evidence_id）。"""
    gw = _gateway(tmp_path)
    r1 = gw.invoke("fixture_repo_lookup", {"repo_name": "langgraph"})
    r2 = gw.invoke("fixture_repo_lookup", {"repo_name": "langgraph"})
    assert r1.evidence_id == r2.evidence_id
    assert r2.cached_from == r1.evidence_id
    assert r2.content_hash  # 内容哈希存在


def test_param_change_new_call(tmp_path: Path) -> None:
    """4.3-4：参数变化产生新调用（新幂等键 + 新 evidence）。"""
    counter = [0]
    gw = _gateway(tmp_path, call_counter=counter)
    r1 = gw.invoke("fixture_repo_lookup", {"repo_name": "langgraph"})
    r2 = gw.invoke("fixture_repo_lookup", {"repo_name": "crewai"})
    assert counter[0] == 2
    assert r2.status == "ok"
    assert r1.evidence_id != r2.evidence_id


def test_tool_subtask_rework_passes_unit(tmp_path: Path) -> None:
    """4.3-5（单元）：工具型子任务返工——首次执行后重跑命中缓存，产物非空，Reviewer 通过。"""
    gw = _gateway(tmp_path)
    researcher = FakeResearcher(gw)
    subtask = _subtask()
    # 首次执行（真实调用）
    first = researcher.run(subtask, [subtask])
    assert gw.tool_calls[-1]["status"] == "ok"
    # 返工重跑（同参数 → 幂等命中 → 缓存复用，handler 不重复执行）
    subtask.rework_count = 1
    result = researcher.run(subtask, [subtask])
    assert result.claims  # 4.3-7：不再产生空产物
    assert result.evidence_refs
    assert gw.tool_calls[-1]["status"] == "cached_success_result"
    assert gw.tool_calls[-1]["cached_from"] == first.evidence_refs[0]
    subtask.execution_result = result
    subtask.evidence_refs = result.evidence_refs
    det = DeterministicReviewer()
    issues = det.check(
        subtask,
        valid_evidence_ids={e["id"] for e in gw.evidence},
        agent_allowed_tools=[],
        used_tool_calls=2,
    )
    assert issues == []


def test_tool_subtask_rework_passes_e2e(tmp_path: Path) -> None:
    """4.3-5（端到端）：scenario:reject-tool-once——s1（工具型）首次驳回后返工通过。"""
    report = run_task(
        "scenario:reject-tool-once",
        token_budget=10000,
        cost_budget=0.5,
        data_dir=tmp_path / "data",
    )
    assert report.status == "completed"
    trace = trace_task(report.run_id, data_dir=tmp_path / "data")
    s1 = next(s for s in trace["subtasks"] if s["subtask_id"] == "s1")
    # 4.3-6：旧审查历史保留（reject → pass 两条）
    assert len(s1["review_history"]) == 2
    assert s1["review_history"][0]["verdict"] == "reject"
    assert s1["review_history"][1]["verdict"] == "pass"
    # 4.3-7：返工产物非空
    assert s1["execution_result"]["claims"]
    assert s1["execution_result"]["evidence_refs"]


def test_old_review_history_kept(tmp_path: Path) -> None:
    """4.3-6：旧审查历史保留（reject→pass 不覆盖）。"""
    report = run_task(
        "scenario:reject-tool-once",
        token_budget=10000,
        cost_budget=0.5,
        data_dir=tmp_path / "data",
    )
    trace = trace_task(report.run_id, data_dir=tmp_path / "data")
    s1 = next(s for s in trace["subtasks"] if s["subtask_id"] == "s1")
    assert [r["verdict"] for r in s1["review_history"]] == ["reject", "pass"]


def test_no_empty_result_and_no_bypass(tmp_path: Path) -> None:
    """4.3-7/8：返工无空产物；工具调用全程经 Tool Gateway（记录含缓存条目）。"""
    report = run_task(
        "scenario:reject-tool-once",
        token_budget=10000,
        cost_budget=0.5,
        data_dir=tmp_path / "data",
    )
    assert report.status == "completed"
    # gateway 记录在 checkpoint 的 tool_calls 中：全部经 gateway 执行/缓存
    assert report.state.tool_calls
    assert all(
        c.status in ("ok", "cached_success_result", "error", "blocked", "skipped")
        for c in report.state.tool_calls
    )
    statuses = [c.status for c in report.state.tool_calls]
    assert "cached_success_result" in statuses
