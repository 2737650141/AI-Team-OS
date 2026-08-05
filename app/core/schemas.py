"""M2 结构化 Schema：AgentSpec / Plan / Subtask / Dependency / Claim / Review / 澄清 / 汇总。

设计约束（004 四/五/六/九/十/十三）：
- spec 类字段由 Planner/Registry 创建，执行者不可修改（代码层纪律 + Pydantic 校验）。
- LLM 输出一律经本模块 Schema 校验后才允许写入 RuntimeState。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


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
    input_refs: list[str] = Field(default_factory=list)
    expected_output: str
    acceptance_criteria: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    token_budget: int = 1000
    tool_call_budget: int = 5


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


class ReviewResult(BaseModel):
    """Reviewer 输出（004 十）。verdict: pass | reject。"""

    verdict: str  # pass | reject
    issues: list[ReviewIssue] = Field(default_factory=list)
    rework_targets: list[str] = Field(default_factory=list)
    accepted_claims: list[str] = Field(default_factory=list)
    rejected_claims: list[str] = Field(default_factory=list)


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
