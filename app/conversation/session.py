"""ConversationSession（PRODUCT-01 REAL GATE，020-B 九~十三）。

会话级 Working Context（**不是长期 Memory**）：
- current_goal / recent_user_turns / recent_assistant_results
- selected_item（"第二个"选中的列表项）
- recent_grounding（最近工具返回的数据，供"刚才那个/那个/它"引用）
- pending_plan（"先别改代码，那写个方案"产生的方案；"第一项/继续"引用）
- current_task_reference / current_project / current_window
- no_write（"先别改代码" = NO_WRITE_CURRENT_SCOPE，会话级约束，新明确授权可解除）

ConversationReferenceResolver 优先级（020-B 十一）：
Current Turn > Conversation Working Context > Current Task > Project Memory。
仅解析明确指代；指代解析不了时返回 clarify 而非硬猜。

持久化：data/runtime/sessions/<session_id>.json（短期，可随时删除）。
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

MAX_TURNS = 10
MAX_GROUNDING = 5

_SECOND_PATTERN = re.compile(r"第\s*([二2两])\s*个")
_FIRST_PATTERN = re.compile(r"第\s*([一1])\s*项")
_CONTINUE_PATTERN = re.compile(r"^(继续|接着|下一步|继续吧|继续做)")
_COMPARE_PATTERN = re.compile(r"跟\s*我们的|和\s*我们的|与\s*我们的|our\s*project")
_REFER_PATTERN = re.compile(r"^(刚才那个|那个|它|这个|这个项目)")
_REPO_PATTERN = re.compile(r"([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)")
_PLAN_PATTERN = re.compile(r"写\s*个?\s*方案|制定方案|出个方案|写方案|做个方案")
_RESULT_PATTERN = re.compile(r"看.*结果|结果呢|怎么样了|看一下结果|结果怎么样")
_SUMMARY_PATTERN = re.compile(
    r"还有没有问题|有没有问题|还有问题吗|还有什么问题|检查一下当前|汇总一下"
)


@dataclass
class PendingPlan:
    title: str
    items: list[str]
    detail: str = ""


@dataclass
class ConversationSession:
    session_id: str
    current_goal: str | None = None
    recent_user_turns: list[str] = field(default_factory=list)
    recent_assistant_results: list[dict[str, Any]] = field(default_factory=list)
    selected_item: str | None = None
    current_project: str = "default"
    current_window: str | None = None
    recent_grounding: list[str] = field(default_factory=list)
    pending_plan: PendingPlan | None = None
    current_task_reference: str | None = None
    no_write: bool = False
    # 024-C ConversationScrollController：每个 conversation 保存的滚动状态
    scroll_top: int = 0
    anchor_message_id: str | None = None
    was_near_bottom: bool = True
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))
    updated_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))

    def set_scroll_state(
        self, *, scroll_top: int, anchor_message_id: str | None, was_near_bottom: bool
    ) -> None:
        """024-C：保存会话滚动状态（离开会话前调用）。

        不刷新 updated_at：滚动保存是 UI 位置记录，不应改变"会话最后活跃时间"
        （否则每次滚动都会让会话在 Recent conversations 中跳到顶部）。
        """
        self.scroll_top = max(0, int(scroll_top))
        self.anchor_message_id = anchor_message_id
        self.was_near_bottom = bool(was_near_bottom)

    # ---- 持久化 ----
    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.pending_plan is not None:
            d["pending_plan"] = asdict(self.pending_plan)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConversationSession":
        pp = data.get("pending_plan")
        data = {k: v for k, v in data.items() if k != "pending_plan"}
        session = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        if pp:
            session.pending_plan = PendingPlan(
                **{k: v for k, v in pp.items() if k in PendingPlan.__dataclass_fields__}
            )
        return session

    @staticmethod
    def path_for(data_dir: Path, session_id: str) -> Path:
        return data_dir / "runtime" / "sessions" / f"{session_id}.json"

    def save(self, data_dir: Path) -> None:
        p = self.path_for(data_dir, self.session_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, data_dir: Path, session_id: str) -> "ConversationSession | None":
        p = cls.path_for(data_dir, session_id)
        if not p.exists():
            return None
        return cls.from_dict(json.loads(p.read_text(encoding="utf-8")))

    def record_turn(self, user_input: str, result: dict[str, Any]) -> None:
        """记录一轮用户输入与助手结果（含列表提取，供"第二个"引用）。"""
        self.recent_user_turns.append(user_input)
        self.recent_user_turns = self.recent_user_turns[-MAX_TURNS:]
        self.recent_assistant_results.append(result)
        self.recent_assistant_results = self.recent_assistant_results[-MAX_TURNS:]
        self.current_goal = user_input
        # 提取候选列表项（"第二个"引用）：优先结果自带 items，否则从 claims 找 repo 全名
        items = list(result.get("items") or [])
        if not items:
            for claim in result.get("claims", []):
                for m in _REPO_PATTERN.findall(str(claim)):
                    if m not in items:
                        items.append(m)
        if items:
            result["items"] = items
        # grounding 更新（最近工具数据/结论）
        summary = result.get("summary") or result.get("final_result") or ""
        if summary:
            self.recent_grounding.append(str(summary)[:500])
            self.recent_grounding = self.recent_grounding[-MAX_GROUNDING:]
        self.current_task_reference = str(result.get("task_id") or "")
        self.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")


@dataclass
class ResolvedTurn:
    """解析结果：goal 为执行目标；action 控制特殊行为。"""

    goal: str
    constraints: dict[str, Any] = field(default_factory=dict)  # {"no_write": bool}
    action: str = "run"  # run | confirm_only | clarify


class ConversationReferenceResolver:
    """指代解析：Current Turn > Working Context > Current Task > Project Memory。

    只解析明确指代（第二个/继续/第一项/刚才那个/它/那个）；无上下文 → clarify。
    """

    def resolve(self, session: ConversationSession, user_input: str) -> ResolvedTurn:
        text = user_input.strip()
        # "先别改代码"：NO_WRITE_CURRENT_SCOPE 会话级约束（020-B 十三）
        if re.search(r"先别改|不要改|别改代码|不改代码|不用改代码", text):
            return ResolvedTurn(
                goal=text,
                constraints={"no_write": True},
                action="confirm_only",
            )
        # "看一下结果/怎么样了"：回显最近结果（Working Context，不调模型）
        if _RESULT_PATTERN.search(text) and session.recent_assistant_results:
            return ResolvedTurn(goal="查看最近结果", action="confirm_only")
        # "还有没有问题/汇总"：基于会话状态确定性总结（020-B 十）
        if _SUMMARY_PATTERN.search(text):
            return ResolvedTurn(goal="总结当前会话进展与潜在问题", action="run")
        # "写个方案/制定方案"（短句，020-B 十）：对象=选中的项目或最近 grounding
        if _PLAN_PATTERN.search(text):
            grounding = session.recent_grounding[-1][:120] if session.recent_grounding else ""
            target = session.selected_item or grounding
            if target:
                return ResolvedTurn(
                    goal=f"为 {target} 制定实施方案（不修改代码，仅输出方案）",
                    action="run",
                )
            return ResolvedTurn(goal=text, action="clarify")
        # "把第一项实施 / 实施..."：明确授权 → 解除 no_write + 引用 plan 第 1 项
        if "实施" in text or "执行" in text:
            m = _FIRST_PATTERN.search(text)
            if m and session.pending_plan and session.pending_plan.items:
                item = session.pending_plan.items[0]
                return ResolvedTurn(
                    goal=f"实施方案第一项：{item}",
                    constraints={"no_write": False},
                    action="run",
                )
            if session.selected_item:
                return ResolvedTurn(
                    goal=text.replace("它", session.selected_item).replace(
                        "那个", session.selected_item
                    ),
                    constraints={"no_write": False},
                    action="run",
                )
            return ResolvedTurn(goal=text, constraints={"no_write": False}, action="run")
        # "继续"：pending_plan/paused 任务优先 Resume（020-B 十二）
        if _CONTINUE_PATTERN.match(text):
            if session.pending_plan is not None:
                return ResolvedTurn(
                    goal=f"继续完善方案：{session.pending_plan.title}",
                    constraints={},
                    action="run",
                )
            if session.current_task_reference:
                return ResolvedTurn(
                    goal=f"继续：{session.current_goal or ''}",
                    constraints={},
                    action="run",
                )
            return ResolvedTurn(goal=text, action="clarify")
        # "第二个"：引用 recent_assistant_results 最后一条的列表第 2 项
        m = _SECOND_PATTERN.search(text)
        if m:
            items = self._recent_items(session)
            if len(items) >= 2:
                session.selected_item = items[1]
                rest = self._strip_reference(text)
                goal = (
                    f"详细研究 {session.selected_item}：{rest}"
                    if rest
                    else f"详细研究 {session.selected_item}"
                )
                return ResolvedTurn(goal=goal, action="run")
            return ResolvedTurn(goal=text, action="clarify")
        # "第一项"：pending_plan 第 1 项
        m = _FIRST_PATTERN.search(text)
        if m:
            if session.pending_plan and session.pending_plan.items:
                return ResolvedTurn(
                    goal=f"查看/执行方案第一项：{session.pending_plan.items[0]}",
                    action="run",
                )
            return ResolvedTurn(goal=text, action="clarify")
        # "刚才那个/那个/它"：最近 grounding
        if _REFER_PATTERN.match(text):
            if session.recent_grounding:
                return ResolvedTurn(
                    goal=f"{text}（基于最近上下文：{session.recent_grounding[-1][:200]}）",
                    action="run",
                )
            return ResolvedTurn(goal=text, action="clarify")
        # "跟我们的项目比较/对比"：附加 selected_item
        if _COMPARE_PATTERN.search(text) and session.selected_item:
            return ResolvedTurn(
                goal=f"比较 {session.selected_item} 与当前项目：{text}",
                action="run",
            )
        return ResolvedTurn(goal=text, action="run")

    @staticmethod
    def _recent_items(session: ConversationSession) -> list[str]:
        for result in reversed(session.recent_assistant_results):
            items = result.get("items") or []
            if items:
                return items
        return []

    @staticmethod
    def _strip_reference(text: str) -> str:
        return re.sub(r"第\s*([二2两])\s*个", "", text).strip(" ，,：:。")
