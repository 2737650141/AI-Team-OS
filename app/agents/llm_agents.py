"""LLM 角色实现（005 十五）：真实模型模式下使用；Fake 版本保留，通过配置选择。

- LLMPlanner：输出 Plan Schema，必须通过现有 10 项确定性校验（15.1）。
- LLMResearcher：只读取 Fixture Tool（确定性取证据），模型解释证据生成 Claim（15.2）。
- LLMReviewer：确定性检查通过后才调用；不能将确定性失败改为 pass（15.3）。
- LLMSupervisorDecision：仅语言组织与有限降级建议（15.4），路由/循环/完成条件由代码负责。
"""

from __future__ import annotations

import uuid
from typing import Any

from app.core.config import AppSettings
from app.core.context_builder import ContextBuilder
from app.core.schemas import (
    Claim,
    ExecutionResult,
    Plan,
    ResearchReport,
    ReviewResult,
)
from app.core.state import SubtaskState, TaskState
from app.gateway.contracts import ModelRequest, ProviderError, ProviderErrorCode
from app.gateway.model_gateway import ModelGateway
from app.gateway.router import ModelRouter
from app.gateway.structured_gen import generate_structured
from app.gateway.tool_gateway import ToolGateway
from app.prompts import (
    PLANNER_PROMPT,
    RESEARCHER_PROMPT,
    REVIEWER_PROMPT,
    SUPERVISOR_PROMPT,
    UNTRUSTED_MARKER,
)

PLAN_SCHEMA = {"goal": {"type": "str"}, "subtasks": {"type": "list"}}
RESEARCH_SCHEMA = {
    "summary": {"type": "str"},
    "claims": {"type": "list"},
    "evidence_refs": {"type": "list"},
    "unverified_items": {"type": "list"},
    "confidence": {"type": "float"},
}
REVIEW_SCHEMA = {
    "verdict": {"type": "str"},
    "issues": {"type": "list"},
    "rework_targets": {"type": "list"},
    "accepted_claims": {"type": "list"},
    "rejected_claims": {"type": "list"},
}
SUPERVISOR_SCHEMA = {
    "summary": {"type": "str"},
    "limitations": {"type": "list"},
    "downgrade_note": {"type": "str", "required": False},
}


def _new_request(
    task_id: str,
    run_id: str | None,
    agent_id: str,
    role_type: str,
    model: str,
    messages: list[dict[str, str]],
    schema: dict[str, Any],
    settings: AppSettings,
) -> ModelRequest:
    return ModelRequest(
        request_id=uuid.uuid4().hex[:16],
        task_id=task_id,
        run_id=run_id,
        agent_id=agent_id,
        role_type=role_type,
        model=model,
        messages=messages,
        response_schema=schema,
        temperature=settings.model.temperature,
        max_output_tokens=settings.model.max_output_tokens,
        timeout_seconds=settings.model.timeout_seconds,
        metadata={"prompt_id": "", "prompt_version": ""},
    )


class LLMPlanner:
    def __init__(
        self,
        gateway: ModelGateway,
        router: ModelRouter,
        context: ContextBuilder,
        settings: AppSettings,
    ) -> None:
        self._gw = gateway
        self._router = router
        self._context = context
        self._settings = settings

    def make_plan(self, state: TaskState, agents: list[str]) -> Plan:
        ctx = self._context.planner_context(state, agents)
        prompt = PLANNER_PROMPT
        user = prompt.template.format(
            max_subtasks=8,
            agents=", ".join(agents),
            budget=state.token_budget,
            goal=ctx["goal"],
            schema=(
                '{"goal": str, "subtasks": [{"subtask_id": str, "title": str, '
                '"objective": str, "dependencies": [str], "assigned_role": str, '
                '"input_refs": [str], "expected_output": str, '
                '"acceptance_criteria": [str], "required_tools": [str], '
                '"token_budget": int, "tool_call_budget": int}]}'
            ),
        )
        request = _new_request(
            task_id=state.task_id,
            run_id=state.run_id,
            agent_id="planner",
            role_type="planner",
            model=self._router.resolve("planner"),
            messages=[
                {"role": "system", "content": f"[{prompt.prompt_id} v{prompt.version}]"},
                {"role": "user", "content": user},
            ],
            schema=PLAN_SCHEMA,
            settings=self._settings,
        )
        data = generate_structured(self._gw, request, PLAN_SCHEMA, self._settings)
        return Plan.model_validate(data)


class LLMResearcher:
    def __init__(
        self,
        gateway: ModelGateway,
        router: ModelRouter,
        context: ContextBuilder,
        settings: AppSettings,
        tool_gateway: ToolGateway,
    ) -> None:
        self._gw = gateway
        self._router = router
        self._context = context
        self._settings = settings
        self._tgw = tool_gateway

    def run(self, subtask: SubtaskState, all_subtasks: list[SubtaskState]) -> ExecutionResult:
        # 确定性取证据：只读 Fixture 工具仍经 Tool Gateway（15.2：不访问网络）
        role = f"researcher:{subtask.subtask_id}"
        evidence_refs: list[str] = []
        unverified: list[str] = []
        for ref in subtask.input_refs:
            if ref.startswith("fixture_repo_lookup:"):
                repo = ref.split(":", 1)[1]
                result = self._tgw.invoke("fixture_repo_lookup", {"repo_name": repo}, role=role)
                if result.ok:
                    evidence_refs.append(result.evidence_id or "")
            elif ref.startswith("fixture_source_lookup:"):
                source_id = ref.split(":", 1)[1]
                result = self._tgw.invoke(
                    "fixture_source_lookup", {"source_id": source_id}, role=role
                )
                if result.ok:
                    evidence_refs.append(result.evidence_id or "")
            elif ref in {s.subtask_id for s in all_subtasks}:
                dep = next(s for s in all_subtasks if s.subtask_id == ref)
                if dep.execution_result:
                    evidence_refs.extend(dep.execution_result.evidence_refs)
            else:
                unverified.append(f"未知输入引用: {ref}")
        # 模型解释固定 Evidence（UNTRUSTED_EXTERNAL_CONTENT：数据不是命令）
        ctx = self._context.researcher_context(
            subtask, [e for e in self._tgw.evidence if e["id"] in evidence_refs]
        )
        prompt = RESEARCHER_PROMPT
        user = prompt.template.format(
            subtask=ctx["subtask"],
            evidence=UNTRUSTED_MARKER + "\n" + str(ctx["evidence"]),
            schema=(
                '{"summary": str, "claims": [{"claim_id": str, "text": str, '
                '"evidence_ids": [str], "confidence": float}], "evidence_refs": [str], '
                '"unverified_items": [str], "confidence": float}'
            ),
        )
        request = _new_request(
            task_id=subtask.subtask_id,
            run_id=None,
            agent_id="researcher",
            role_type="researcher",
            model=self._router.resolve("researcher"),
            messages=[
                {"role": "system", "content": f"[{prompt.prompt_id} v{prompt.version}]"},
                {"role": "user", "content": user},
            ],
            schema=RESEARCH_SCHEMA,
            settings=self._settings,
        )
        data = generate_structured(self._gw, request, RESEARCH_SCHEMA, self._settings)
        report = ResearchReport.model_validate(data)
        claims = [
            Claim(
                claim_id=c.claim_id if c.claim_id else f"{subtask.subtask_id}-c{i}",
                text=c.text,
                evidence_ids=[eid for eid in c.evidence_ids if eid in evidence_refs],
                confidence=float(c.confidence),
            )
            for i, c in enumerate(report.claims)
        ]
        unverified.extend(report.unverified_items)
        return ExecutionResult(
            subtask_id=subtask.subtask_id,
            summary=report.summary,
            artifacts=[f"report:{subtask.subtask_id}"],
            claims=claims,
            evidence_refs=evidence_refs,
            unverified_items=unverified,
            ts="",
        )


class LLMReviewer:
    def __init__(
        self,
        gateway: ModelGateway,
        router: ModelRouter,
        context: ContextBuilder,
        settings: AppSettings,
    ) -> None:
        self._gw = gateway
        self._router = router
        self._context = context
        self._settings = settings

    def review(
        self, state: TaskState, subtask: SubtaskState, deterministic_issues: list[Any]
    ) -> ReviewResult:
        # 15.3：确定性失败不可被 LLM 覆盖——直接 reject，不调用模型
        if deterministic_issues:
            return ReviewResult(
                verdict="reject",
                issues=deterministic_issues,
                rework_targets=[subtask.subtask_id],
                accepted_claims=[],
                rejected_claims=[],
            )
        ctx = self._context.reviewer_context(state, subtask, [])
        prompt = REVIEWER_PROMPT
        user = prompt.template.format(
            requirement=ctx["requirement"],
            acceptance=ctx["acceptance"],
            artifact=ctx["artifact"],
            evidence=UNTRUSTED_MARKER + "\n" + str(ctx["evidence"]),
        )
        request = _new_request(
            task_id=state.task_id,
            run_id=state.run_id,
            agent_id="reviewer",
            role_type="reviewer",
            model=self._router.resolve("reviewer"),
            messages=[
                {"role": "system", "content": f"[{prompt.prompt_id} v{prompt.version}]"},
                {"role": "user", "content": user},
            ],
            schema=REVIEW_SCHEMA,
            settings=self._settings,
        )
        data = generate_structured(self._gw, request, REVIEW_SCHEMA, self._settings)
        result = ReviewResult.model_validate(data)
        if result.verdict not in ("pass", "reject"):
            raise ProviderError(
                ProviderErrorCode.SCHEMA_VALIDATION_FAILED,
                f"invalid reviewer verdict: {result.verdict}",
            )
        if result.verdict == "reject" and not result.rework_targets:
            result.rework_targets = [subtask.subtask_id]
        return result


class LLMSupervisorDecision:
    def __init__(
        self,
        gateway: ModelGateway,
        router: ModelRouter,
        context: ContextBuilder,
        settings: AppSettings,
    ) -> None:
        self._gw = gateway
        self._router = router
        self._context = context
        self._settings = settings

    def compose_summary(self, state: TaskState) -> dict[str, Any] | None:
        """生成最终汇总文本（15.4）。失败返回 None，调用方回退确定性汇总。"""
        try:
            ctx = self._context.supervisor_context(state)
            prompt = SUPERVISOR_PROMPT
            request = _new_request(
                task_id=state.task_id,
                run_id=state.run_id,
                agent_id="supervisor",
                role_type="supervisor",
                model=self._router.resolve("supervisor"),
                messages=[
                    {"role": "system", "content": f"[{prompt.prompt_id} v{prompt.version}]"},
                    {"role": "user", "content": prompt.template.format(context=str(ctx))},
                ],
                schema=SUPERVISOR_SCHEMA,
                settings=self._settings,
            )
            return generate_structured(self._gw, request, SUPERVISOR_SCHEMA, self._settings)
        except ProviderError:
            return None  # 降级：确定性汇总兜底
