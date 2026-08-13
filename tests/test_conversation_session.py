"""ConversationSession / ConversationReferenceResolver 测试（020-B 九~十三）。

离线（fake 模式）验证 10-turn 会话：指代（第二个/继续/第一项/刚才那个）不再
因"无上下文"暂停；"先别改代码"为会话级只读约束；"把第一项实施"为新授权。
"""

from __future__ import annotations

from pathlib import Path

from app.conversation.service import run_conversation_turn
from app.conversation.session import (
    ConversationReferenceResolver,
    ConversationSession,
    PendingPlan,
)


# ---------- Resolver 纯逻辑 ----------
def _session_with_items(items: list[str]) -> ConversationSession:
    s = ConversationSession(session_id="t")
    s.record_turn(
        "找几个项目",
        {"status": "completed", "claims": items, "summary": "找到项目", "task_id": "x1"},
    )
    return s


def test_resolver_second_item() -> None:
    s = _session_with_items(["langgraph-ai/langgraph", "crewAIInc/crewAI"])
    r = ConversationReferenceResolver().resolve(s, "第二个详细看看")
    assert r.action == "run"
    assert "crewAIInc/crewAI" in r.goal
    assert s.selected_item == "crewAIInc/crewAI"


def test_resolver_second_missing_context_clarifies() -> None:
    s = ConversationSession(session_id="t")
    r = ConversationReferenceResolver().resolve(s, "第二个")
    assert r.action == "clarify"


def test_resolver_continue_with_pending_plan() -> None:
    s = ConversationSession(session_id="t")
    s.pending_plan = PendingPlan(title="方案", items=["a", "b"])
    r = ConversationReferenceResolver().resolve(s, "继续")
    assert r.action == "run"
    assert "方案" in r.goal


def test_resolver_continue_without_context_clarifies() -> None:
    s = ConversationSession(session_id="t")
    r = ConversationReferenceResolver().resolve(s, "继续")
    assert r.action == "clarify"


def test_resolver_first_item_of_plan() -> None:
    s = ConversationSession(session_id="t")
    s.pending_plan = PendingPlan(title="方案", items=["第一项：接入真实 GitHub", "第二项：缓存"])
    r = ConversationReferenceResolver().resolve(s, "第一项")
    assert r.action == "run"
    assert "第一项：接入真实 GitHub" in r.goal


def test_resolver_no_write_constraint() -> None:
    s = ConversationSession(session_id="t")
    r = ConversationReferenceResolver().resolve(s, "先别改代码")
    assert r.action == "confirm_only"
    assert r.constraints.get("no_write") is True


def test_resolver_implement_first_item_authorizes() -> None:
    s = ConversationSession(session_id="t")
    s.pending_plan = PendingPlan(title="方案", items=["接入真实 GitHub", "加缓存"])
    r = ConversationReferenceResolver().resolve(s, "把第一项实施")
    assert r.action == "run"
    assert r.constraints.get("no_write") is False
    assert "接入真实 GitHub" in r.goal


def test_resolver_recent_grounding_reference() -> None:
    s = ConversationSession(session_id="t")
    s.record_turn(
        "查项目",
        {
            "status": "completed",
            "claims": [],
            "summary": "obra/superpowers 很热门",
            "task_id": "x2",
        },
    )
    r = ConversationReferenceResolver().resolve(s, "刚才那个项目详细看看")
    assert r.action == "run"
    assert "obra/superpowers" in r.goal


def test_resolver_compare_attaches_selected_item() -> None:
    s = _session_with_items(["langgraph-ai/langgraph", "crewAIInc/crewAI"])
    s.selected_item = "crewAIInc/crewAI"
    r = ConversationReferenceResolver().resolve(s, "跟我们的项目比较一下")
    assert "crewAIInc/crewAI" in r.goal


def test_explicit_implementation_binds_controlled_project(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    class Report:
        status = "completed"
        task_id = "task"
        run_id = "run"
        call_count = 1
        tool_call_count = 0
        usage = {"tokens": 1}

        class state:
            failure_code = None
            complexity = "standard"
            rework_count = 0
            replan_count = 0
            final_result = "done"
            subtasks = []

    def fake_run(goal, **kwargs):
        captured.update(goal=goal, **kwargs)
        return Report()

    monkeypatch.setattr("app.conversation.service.run_task", fake_run)
    session = ConversationSession(
        session_id="bound",
        current_project="sample-python",
        pending_plan=PendingPlan(title="p", items=["修复失败测试"]),
        no_write=True,
    )
    session.save(tmp_path)
    _, result = run_conversation_turn(
        "bound", "把第一项实施", tmp_path, project_alias="sample-python"
    )
    assert result["status"] == "completed"
    assert captured["goal"].startswith("sandbox_conversation:")
    assert captured["model_overrides"] == {"project_alias": "sample-python"}


def test_incremental_comparison_reuses_working_context(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    class Report:
        status = "completed"
        task_id = "task"
        run_id = "run"
        call_count = 1
        tool_call_count = 0
        usage = {"tokens": 1}

        class state:
            failure_code = None
            complexity = "simple"
            rework_count = 0
            replan_count = 0
            final_result = "done"
            subtasks = []

    def fake_run(goal, **kwargs):
        captured["goal"] = goal
        return Report()

    monkeypatch.setattr("app.conversation.service.run_task", fake_run)
    session = ConversationSession(session_id="follow", selected_item="crewAIInc/crewAI")
    session.record_turn(
        "第二个详细看看", {"summary": "CrewAI 使用角色式编排", "status": "completed"}
    )
    session.save(tmp_path)
    run_conversation_turn("follow", "跟我们的项目比较一下", tmp_path)
    assert captured["goal"].startswith("conversation_followup:")
    assert "CrewAI 使用角色式编排" in captured["goal"]


# ---------- run_conversation_turn 全流程（fake 离线） ----------
TEN_TURN = [
    "找几个最近热门的 Agent 项目",
    "第二个详细看看",
    "跟我们的项目比较一下",
    "哪些东西值得我们借鉴",
    "先别改代码",
    "那先写个方案",
    "继续",
    "把第一项实施",
    "看一下结果",
    "还有没有问题",
]


def test_ten_turn_session_fake(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    session_id = "acceptance-session"
    results: list[dict] = []
    for i, user_input in enumerate(TEN_TURN, start=1):
        session, result = run_conversation_turn(session_id, user_input, data_dir, model_mode="fake")
        results.append(result)
        # 指代类不得以 clarify 卡死（无上下文暂停）
        assert result.get("action") != "clarify", f"turn{i} clarified: {user_input}"
        assert result["status"] in ("completed", "confirmed", "blocked", "paused"), (
            f"turn{i} unexpected status: {result['status']}"
        )
        print(
            f"turn{i}: {user_input[:24]} -> {result['status']} ({result.get('summary', '')[:40]})"
        )
    # 关键会话状态断言
    assert session.no_write is False  # turn8 "实施" 解除了 turn5 的只读约束
    assert session.selected_item is not None  # turn2 选中了第二项
    assert session.pending_plan is not None  # turn6 生成了方案
    assert len(session.recent_user_turns) >= 5
