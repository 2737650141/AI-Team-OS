"""M2 黄金任务工作流测试（GT-01/02/05/07/11，测试要求 8-21）。"""

from __future__ import annotations

import json
from pathlib import Path

from app.agents.researcher import FakeResearcher
from app.agents.reviewer import DeterministicReviewer, FakeReviewer
from app.core.state import SubtaskState
from app.gateway.audit import AuditLog
from app.gateway.tool_gateway import ToolGateway
from app.runner import run_task, trace_task
from app.tools.fixture_repo import FixtureRepositoryLookupTool, FixtureSourceLookupTool
from tests.conftest import FIXTURE_REPOS

SOURCES = Path(__file__).resolve().parent / ".." / "app" / "tools" / "fixtures" / "sources.json"


def _tool_gateway(tmp_path: Path) -> ToolGateway:
    gw = ToolGateway(audit=AuditLog(tmp_path / "audit.jsonl"), task_id="t-m2")
    gw.register(FixtureRepositoryLookupTool(FIXTURE_REPOS).spec())
    gw.register(FixtureSourceLookupTool(SOURCES).spec())
    return gw


# ---------- GT-01 offline：并行研究 + 证据 + Reviewer 通过才完成 ----------
def test_gt01_offline_compare(tmp_path: Path) -> None:
    report = run_task(
        "github_compare_team",
        token_budget=10000,
        cost_budget=0.5,
        data_dir=tmp_path / "data",
    )
    assert report.status == "completed"
    final = json.loads(report.state.final_result)
    assert final["decision"] == "accept"
    assert len(final["evidence_index"]) >= 2  # 两条证据（s1/s2）
    # Evidence ID 全部真实存在（测试要求 10）
    valid_ids = {e.id for e in report.state.evidence}
    for eid in final["evidence_index"]:
        assert eid in valid_ids
    # 全部子任务通过
    assert all(s.runtime_status == "passed" for s in report.state.subtasks)
    # 工具调用全部为只读 Fixture（无网络）
    assert all(
        (c.get("tool") if isinstance(c, dict) else c.tool).startswith("fixture_")
        for c in report.state.tool_calls
    )


# ---------- GT-05：冲突来源核查 ----------
def test_gt05_conflicting_sources_marked(tmp_path: Path) -> None:
    report = run_task(
        "scenario:parallel",
        token_budget=10000,
        cost_budget=0.5,
        data_dir=tmp_path / "data",
    )
    assert report.status == "completed"
    trace = trace_task(report.run_id, data_dir=tmp_path / "data")
    # 两个 langgraph 来源结论相反 → 显式标记矛盾（unverified_items）
    all_unverified = [
        item for s in trace["subtasks"] for item in s["execution_result"]["unverified_items"]
    ]
    assert any("矛盾" in item for item in all_unverified)
    # 矛盾来源的 claim 置信度低（0.3）且带 evidence（测试要求 10/11）
    t2 = next(s for s in trace["subtasks"] if s["subtask_id"] == "t2")
    claims = t2["execution_result"]["claims"]
    assert claims[0]["confidence"] == 0.3
    assert claims[0]["evidence_ids"]


# ---------- GT-07：fan-out/fan-in（不依赖耗时阈值，事件序列证据） ----------
def test_gt07_parallel_fanout_fanin_events(tmp_path: Path) -> None:
    """并行验证：exec_subtask 事件全部在 review_all 之前；状态分片无覆盖（测试要求 8/9）。"""
    from langgraph.checkpoint.sqlite import SqliteSaver

    from app.core.budget import BudgetController
    from app.core.state import TaskState
    from app.gateway.model_gateway import DeterministicFakeModel, ModelGateway
    from app.graph import build_graph

    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    state = TaskState(
        task_id="t-par",
        run_id="r-par",
        user_goal="scenario:parallel",
        token_budget=10000,
        cost_budget=0.5,
    )
    budget = BudgetController(10000, 0.5)
    audit = AuditLog(data_dir / "audit.jsonl")
    gw = ModelGateway(
        provider=DeterministicFakeModel(), budget=budget, audit=audit, task_id="t-par"
    )
    tgw = _tool_gateway(tmp_path)
    conn = __import__("sqlite3").connect(str(data_dir / "checkpoints.db"), check_same_thread=False)
    compiled = build_graph(gw, tgw, goal="scenario:parallel").compile(
        checkpointer=SqliteSaver(conn)
    )

    events = list(
        compiled.stream(state.model_dump(), config={"configurable": {"thread_id": "r-par"}})
    )
    # 事件格式为 {node_name: output}；node_name 是事件 dict 的唯一 key
    node_seq = [next(iter(e)) for e in events if isinstance(e, dict) and e]
    exec_count = node_seq.count("exec_subtask")
    assert exec_count >= 3  # t1/t2/t3 各一次（可能含第二轮）
    # 所有 exec 事件都在首次 review_all 之前开始（fan-in 前开始，测试要求 9）
    first_review = node_seq.index("review_all")
    exec_indexes = [i for i, n in enumerate(node_seq) if n == "exec_subtask"]
    assert all(i < first_review for i in exec_indexes)

    # stream 已完整执行；从 checkpoint 读取最终状态（勿在同一 thread 重复 invoke，
    # 否则幂等键命中导致工具调用被 skipped）
    snapshot = compiled.get_state(config={"configurable": {"thread_id": "r-par"}})
    final = TaskState.model_validate(snapshot.values)
    assert final.current_status == "completed"
    # 状态分片无覆盖（测试要求 8）：三个子任务 execution_result 各自独立且 claims 完整
    t_results = {s.subtask_id: s for s in final.subtasks}
    assert len(t_results) == 3
    for sid in ("t1", "t2", "t3"):
        st = t_results[sid]
        assert st.execution_result is not None
        assert len(st.execution_result.claims) == 1  # 各来源一个 claim，未被覆盖
    conn.close()


# ---------- GT-11：Reviewer 驳回并定向返工 ----------
def test_gt11_reject_once_then_targeted_rework(tmp_path: Path) -> None:
    report = run_task(
        "scenario:reject-once",
        token_budget=10000,
        cost_budget=0.5,
        data_dir=tmp_path / "data",
    )
    assert report.status == "completed"
    trace = trace_task(report.run_id, data_dir=tmp_path / "data")
    by_id = {s["subtask_id"]: s for s in trace["subtasks"]}
    # 已通过子任务不重跑（测试要求 16）：s1/s2 rework_count=0
    assert by_id["s1"]["rework_count"] == 0
    assert by_id["s2"]["rework_count"] == 0
    # 定向返工（测试要求 14）：仅 s3 重跑一次
    assert by_id["s3"]["rework_count"] == 1
    # 历史保留（004 十一）：s3 有两条 review_history（reject + pass），不覆盖
    assert len(by_id["s3"]["review_history"]) == 2
    assert by_id["s3"]["review_history"][0]["verdict"] == "reject"
    assert by_id["s3"]["review_history"][1]["verdict"] == "pass"
    # 最终全部通过
    assert all(s["runtime_status"] == "passed" for s in trace["subtasks"])


def test_rework_limit_exceeded(tmp_path: Path) -> None:
    """返工上限（测试要求 15）：always-reject 场景 → failed/rework_limit_exceeded。"""
    report = run_task(
        "scenario:always-reject",
        token_budget=10000,
        cost_budget=0.5,
        data_dir=tmp_path / "data",
    )
    assert report.status == "failed"
    assert report.state.failure_code == "rework_limit_exceeded"


# ---------- GT-02 澄清：轮次上限（跨进程恢复见 test_resume_integration） ----------
def test_clarification_round_limit_logic() -> None:
    from app.graph import MAX_CLARIFICATION_ROUNDS, needs_clarification

    assert needs_clarification("vague_goal") is True
    assert needs_clarification("github_compare_team") is False
    # 3 轮后仍模糊 → 信息不足失败（004 十三，由 ingest 判定）
    assert MAX_CLARIFICATION_ROUNDS == 3


# ---------- Reviewer 确定性拒绝不可覆盖（测试要求 12/13） ----------
def test_reviewer_deterministic_reject_not_overridable(tmp_path: Path) -> None:
    subtask = SubtaskState(
        subtask_id="x1",
        title="t",
        objective="o",
        dependencies=[],
        assigned_role="researcher",
        input_refs=[],
        expected_output="r",
        acceptance_criteria=["a"],
        required_tools=["fixture_repo_lookup"],
        token_budget=100,
        tool_call_budget=1,
    )
    # 构造无证据 claim 的执行结果（researcher 正常路径不会产生，直接构造）
    from app.core.schemas import Claim, ExecutionResult

    subtask.execution_result = ExecutionResult(
        subtask_id="x1",
        summary="s",
        claims=[Claim(claim_id="c1", text="无证据结论", evidence_ids=[])],
        ts="t",
    )
    det = DeterministicReviewer()
    issues = det.check(subtask, valid_evidence_ids=set(), agent_allowed_tools=[], used_tool_calls=0)
    codes = {i.code for i in issues}
    assert "claim_without_evidence" in codes
    # 确定性失败时 Fake Reviewer（default 场景）必须 reject，不能改为通过（测试要求 13）
    result = FakeReviewer().review(subtask, issues)
    assert result.verdict == "reject"
    assert result.rework_targets == ["x1"]


def test_reviewer_pass_when_deterministic_clean(tmp_path: Path) -> None:
    gw = _tool_gateway(tmp_path)
    researcher = FakeResearcher(gw)
    subtask = SubtaskState(
        subtask_id="r1",
        title="repo",
        objective="o",
        dependencies=[],
        assigned_role="researcher",
        input_refs=["fixture_repo_lookup:langgraph"],
        expected_output="r",
        acceptance_criteria=["a"],
        required_tools=["fixture_repo_lookup"],
        token_budget=100,
        tool_call_budget=2,
    )
    result = researcher.run(subtask, [subtask])
    assert result.claims and all(c.evidence_ids for c in result.claims)  # 测试要求 10/11
    subtask.execution_result = result
    subtask.evidence_refs = result.evidence_refs
    det = DeterministicReviewer()
    issues = det.check(
        subtask,
        valid_evidence_ids={e["id"] for e in gw.evidence},
        agent_allowed_tools=[],
        used_tool_calls=1,
    )
    assert issues == []
    review = FakeReviewer().review(subtask, issues)
    assert review.verdict == "pass"


# ---------- 无网络环境全测试通过（测试要求 22） ----------
def test_app_has_no_network_imports() -> None:
    import re

    root = Path(__file__).resolve().parent.parent / "app"
    banned = re.compile(
        r"^\s*(import|from)\s+(requests|urllib|http\.client|socket|aiohttp)\b", re.M
    )
    offenders = [str(p) for p in root.rglob("*.py") if banned.search(p.read_text(encoding="utf-8"))]
    assert offenders == [], f"app/ 存在网络导入: {offenders}"
