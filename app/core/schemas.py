"""M2 结构化 Schema：AgentSpec / Plan / Subtask / Dependency / Claim / Review / 澄清 / 汇总。

设计约束（004 四/五/六/九/十/十三）：
- spec 类字段由 Planner/Registry 创建，执行者不可修改（代码层纪律 + Pydantic 校验）。
- LLM 输出一律经本模块 Schema 校验后才允许写入 RuntimeState。
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class AgentSpec(BaseModel):
    """Agent 注册描述（004 五）。Registry 由确定性代码管理，LLM 不得创建/修改。"""

    agent_id: str
    role_type: str  # supervisor | planner | researcher | executor | reviewer
    display_name: str
    goal: str
    instructions: str
    allowed_tools: list[str] = Field(default_factory=list)
    model_scenario: str = "fake"
    token_limit: int = 32000
    max_tool_calls: int = 10
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class Dependency(BaseModel):
    subtask_id: str
    depends_on: list[str] = Field(default_factory=list)


class SubtaskSpec(BaseModel):
    """子任务 spec（Planner 创建后不可被执行者修改，004 四）。"""

    subtask_id: str
    title: str
    objective: str
    dependencies: list[str] = Field(default_factory=list)
    assigned_role: str  # role_type
    capability_required: str | None = None
    task_type: str | None = None
    input_refs: list[str] = Field(default_factory=list)
    expected_output: str
    deliverable: str | None = None
    acceptance_criteria: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    token_budget: int = 1000
    tool_call_budget: int = 5

    @model_validator(mode="after")
    def fill_orchestration_contract(self) -> "SubtaskSpec":
        if self.capability_required is None:
            self.capability_required = (
                "code_change" if self.assigned_role == "executor" else "research"
            )
        if self.task_type is None:
            self.task_type = self.capability_required
        if self.deliverable is None:
            self.deliverable = self.expected_output
        return self


class Plan(BaseModel):
    goal: str
    subtasks: list[SubtaskSpec] = Field(default_factory=list)


class Claim(BaseModel):
    """Researcher 输出中的单条结论（004 九）。"""

    claim_id: str
    text: str
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class ResearchReport(BaseModel):
    """Researcher 结构化输出（004 九）。无 evidence 的 Claim 必须标记未验证。"""

    summary: str
    claims: list[Claim] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    unverified_items: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ExecutionResult(BaseModel):
    """子任务执行结果（Specialist 提交 proposal，由确定性节点写入，004 四）。"""

    subtask_id: str
    summary: str
    artifacts: list[str] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    unverified_items: list[str] = Field(default_factory=list)
    ts: str
    metadata: dict[str, Any] = Field(default_factory=dict)  # M3-C：审批/补丁/测试报告引用


class ReviewIssue(BaseModel):
    code: str
    message: str
    subtask_id: str | None = None


class ReviewStatus(str, Enum):
    PASS = "PASS"
    PASS_WITH_NOTES = "PASS_WITH_NOTES"
    REWORK = "REWORK"
    BLOCK = "BLOCK"


class CriterionResult(BaseModel):
    criterion: str
    status: Literal["PASS", "FAIL", "NOT_APPLICABLE"]
    evidence_refs: list[str] = Field(default_factory=list)
    note: str | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_provider_aliases(cls, data: Any) -> Any:
        """Accept one unambiguous provider synonym, then validate strictly."""
        if not isinstance(data, dict):
            return data
        values = dict(data)
        if not values.get("status") and values.get("result"):
            values["status"] = values.pop("result")
        return values


class ReworkItem(BaseModel):
    failure_code: str
    target_subtask: str
    target_role: str
    failed_criterion: str
    required_change: str = Field(min_length=1)
    why_it_matters: str
    verification_required: str


class ReviewResult(BaseModel):
    """Four-state reviewer result with legacy checkpoint compatibility."""

    status: ReviewStatus = ReviewStatus.PASS
    verdict: str | None = None  # legacy: pass | reject
    summary: str = ""
    criteria_results: list[CriterionResult] = Field(default_factory=list)
    blocking_issues: list[ReviewIssue] = Field(default_factory=list)
    rework_items: list[ReworkItem] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    issues: list[ReviewIssue] = Field(default_factory=list)
    rework_targets: list[str] = Field(default_factory=list)
    accepted_claims: list[str] = Field(default_factory=list)
    rejected_claims: list[str] = Field(default_factory=list)
    # PRODUCT-01：结构化拒绝字段（reject 时必须填写）
    required_change: str | None = None  # 具体要求的修改内容
    target_role: str | None = None  # 返工应由哪个角色执行
    retryable: bool = True  # 是否允许重试（False = 必须 replan，禁止盲重试）

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_verdict(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        values = dict(data)
        legacy = bool(values.get("verdict")) and not values.get("status")
        for name in (
            "criteria_results",
            "blocking_issues",
            "rework_items",
            "notes",
            "evidence_refs",
            "issues",
            "rework_targets",
            "accepted_claims",
            "rejected_claims",
        ):
            if values.get(name) is None:
                values[name] = []
        if values.get("summary") is None:
            values["summary"] = ""
        if values.get("confidence") is None:
            values["confidence"] = 0.5
        if values.get("retryable") is None:
            values["retryable"] = True
        verdict = str(values.get("verdict") or "").lower()
        if not values.get("status"):
            values["status"] = "PASS" if verdict == "pass" else "REWORK"
        if not verdict:
            status = str(values["status"]).upper()
            values["verdict"] = "pass" if status in {"PASS", "PASS_WITH_NOTES"} else "reject"
        if legacy and str(values.get("status", "")).upper() == "REWORK":
            issues = values.get("issues") or []
            targets = values.get("rework_targets") or []
            if not values.get("required_change"):
                messages = [
                    str(item.get("message", ""))
                    for item in issues
                    if isinstance(item, dict) and item.get("message")
                ]
                values["required_change"] = "; ".join(messages[:5]) or "修正未通过的验收条件"
            if not values.get("target_role"):
                # Old checkpoints did not persist a role in ReviewResult. The graph
                # replaces this compatibility marker with the actual subtask role.
                values["target_role"] = "assigned_role"
            if not values.get("summary"):
                values["summary"] = "需要定向返工"
            if not values.get("rework_targets") and targets:
                values["rework_targets"] = targets
        return values

    @model_validator(mode="after")
    def validate_review_contract(self) -> "ReviewResult":
        self.verdict = (
            "pass"
            if self.status in {ReviewStatus.PASS, ReviewStatus.PASS_WITH_NOTES}
            else "reject"
        )
        if self.status is ReviewStatus.REWORK:
            if not self.required_change and self.rework_items:
                self.required_change = self.rework_items[0].required_change
            if not self.target_role and self.rework_items:
                self.target_role = self.rework_items[0].target_role
            if not self.required_change or not self.target_role:
                raise ValueError("REWORK requires required_change and target_role")
        if self.status is ReviewStatus.BLOCK:
            self.retryable = False
        return self


class ClarificationRecord(BaseModel):
    """澄清历史（004 十三）。只追加，不覆盖。"""

    clarification_id: str
    question: str
    answer: str | None = None
    ts: str


class ClarificationPayload(BaseModel):
    """澄清恢复值（004 十三）：对应 clarification_id，拒绝空答案，不能修改预算/原始输入。"""

    clarification_id: str
    answer: str = Field(min_length=1)


class ApprovalPayload(BaseModel):
    """审批恢复值（007 5.4）：interrupt 后用户决定（approved/rejected）。"""

    approval_id: str = Field(min_length=1)
    decision: Literal["approved", "rejected"] = "approved"
    reason: str | None = Field(default=None, max_length=500)


class FinalReport(BaseModel):
    """最终汇总（004 十四）。不得把"模型给出答案"直接等同于"任务完成"。"""

    summary: str
    decision: str
    evidence_index: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    unverified_items: list[str] = Field(default_factory=list)
    execution_summary: dict[str, Any] = Field(default_factory=dict)
