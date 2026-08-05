"""Reviewer（004 十）：第一层确定性审查 + 第二层结构化 Fake Reviewer。

确定性审查不通过时，禁止 LLM 将其改为通过（第二层直接 reject）。
Reviewer 只接收：原始要求、验收条件、产物、Evidence、确定性检查结果——
不接收 Researcher/Planner 的隐藏推理，不接收 Supervisor 的主观总结。
"""

from __future__ import annotations

from app.core.schemas import ReviewIssue, ReviewResult
from app.core.state import SubtaskState

# 集中配置：最大返工次数（004 十一，禁止散落硬编码）
MAX_REWORK = 2


class DeterministicReviewer:
    """第一层：确定性审查。所有检查项均为硬性规则。"""

    def check(
        self,
        subtask: SubtaskState,
        valid_evidence_ids: set[str],
        agent_allowed_tools: list[str],
        used_tool_calls: int,
    ) -> list[ReviewIssue]:
        issues: list[ReviewIssue] = []

        # 产物是否存在
        if subtask.execution_result is None:
            issues.append(
                ReviewIssue(
                    code="missing_artifact", message="无执行产物", subtask_id=subtask.subtask_id
                )
            )
            return issues  # 产物缺失时其余检查无意义

        # Evidence ID 是否真实存在
        for eid in subtask.evidence_refs:
            if eid not in valid_evidence_ids:
                issues.append(
                    ReviewIssue(
                        code="unknown_evidence",
                        message=f"evidence 不存在: {eid}",
                        subtask_id=subtask.subtask_id,
                    )
                )

        # 每个关键 Claim 是否有证据
        for claim in subtask.execution_result.claims:
            if not claim.evidence_ids:
                issues.append(
                    ReviewIssue(
                        code="claim_without_evidence",
                        message=f"claim {claim.claim_id} 无证据",
                        subtask_id=subtask.subtask_id,
                    )
                )
            for eid in claim.evidence_ids:
                if eid not in valid_evidence_ids:
                    issues.append(
                        ReviewIssue(
                            code="claim_bad_evidence",
                            message=f"claim {claim.claim_id} 引用不存在的 evidence {eid}",
                            subtask_id=subtask.subtask_id,
                        )
                    )

        # 工具白名单是否违反：产物 evidence 对应的工具必须来自角色白名单
        # （M2 简化：工具执行由 Tool Gateway 强制白名单，此处检查产物 claims 引用存在性即可）

        # 子任务验收条件是否满足（确定性近似：产物 summary 非空 + 有 claims 或显式未验证标记）
        if not subtask.execution_result.summary:
            issues.append(
                ReviewIssue(
                    code="empty_summary", message="产物 summary 为空", subtask_id=subtask.subtask_id
                )
            )
        if not subtask.execution_result.claims and not subtask.execution_result.unverified_items:
            issues.append(
                ReviewIssue(
                    code="no_content",
                    message="产物既无 claims 也无 unverified_items",
                    subtask_id=subtask.subtask_id,
                )
            )
        # 返工轮次：重跑时全部工具调用被幂等跳过且无新证据 → 空产物拒绝
        # （防止旧证据被覆盖后以空产物误判 pass，004 十一）
        if (
            subtask.rework_count > 0
            and not subtask.execution_result.claims
            and not subtask.execution_result.evidence_refs
        ):
            issues.append(
                ReviewIssue(
                    code="rework_empty_result",
                    message="返工结果为空：无 claims 且无新 evidence",
                    subtask_id=subtask.subtask_id,
                )
            )

        # 预算是否超限（工具调用次数预算）
        if used_tool_calls > subtask.tool_call_budget:
            issues.append(
                ReviewIssue(
                    code="tool_call_budget_exceeded",
                    message=f"工具调用 {used_tool_calls} 超过预算 {subtask.tool_call_budget}",
                    subtask_id=subtask.subtask_id,
                )
            )

        # 输出 Schema 是否有效（ExecutionResult 已 Pydantic 校验；此处校验 claim_id 唯一）
        claim_ids = [c.claim_id for c in subtask.execution_result.claims]
        if len(set(claim_ids)) != len(claim_ids):
            issues.append(
                ReviewIssue(
                    code="duplicate_claim_id",
                    message="claim_id 重复",
                    subtask_id=subtask.subtask_id,
                )
            )

        return issues


class FakeReviewer:
    """第二层：结构化评审。确定性 issues 存在时直接 reject（不可被 LLM 覆盖）。"""

    def __init__(self, review_scenario: str = "default") -> None:
        self._scenario = review_scenario

    def review(
        self, subtask: SubtaskState, deterministic_issues: list[ReviewIssue]
    ) -> ReviewResult:
        if deterministic_issues:
            return ReviewResult(
                verdict="reject",
                issues=deterministic_issues,
                rework_targets=[subtask.subtask_id],
                accepted_claims=[],
                rejected_claims=[
                    c.claim_id
                    for c in (subtask.execution_result.claims if subtask.execution_result else [])
                ],
            )
        # 确定性通过后：结构化评审（场景驱动）
        if self._scenario == "review_always_reject":
            return ReviewResult(
                verdict="reject",
                issues=[
                    ReviewIssue(
                        code="scenario_always_reject",
                        message="测试场景：始终拒绝",
                        subtask_id=subtask.subtask_id,
                    )
                ],
                rework_targets=[subtask.subtask_id],
                accepted_claims=[],
                rejected_claims=[
                    c.claim_id
                    for c in (subtask.execution_result.claims if subtask.execution_result else [])
                ],
            )
        if (
            self._scenario == "review_reject_once_then_pass"
            and subtask.subtask_id == "s3"
            and len(subtask.review_history) == 0
        ):
            # GT-11：仅汇总子任务 s3 首次评审拒绝一次（配合 researcher 首次缺证据注入）
            return ReviewResult(
                verdict="reject",
                issues=[
                    ReviewIssue(
                        code="scenario_reject_once",
                        message="测试场景：首次拒绝",
                        subtask_id=subtask.subtask_id,
                    )
                ],
                rework_targets=[subtask.subtask_id],
                accepted_claims=[],
                rejected_claims=[],
            )
        if (
            self._scenario == "review_reject_tool_once"
            and subtask.subtask_id == "s1"
            and len(subtask.review_history) == 0
        ):
            # 004 4.2：工具型子任务首次拒绝一次 → 返工时缓存命中（handler 不重跑）→ 通过
            return ReviewResult(
                verdict="reject",
                issues=[
                    ReviewIssue(
                        code="scenario_reject_tool_once",
                        message="测试场景：工具型首次拒绝",
                        subtask_id=subtask.subtask_id,
                    )
                ],
                rework_targets=[subtask.subtask_id],
                accepted_claims=[],
                rejected_claims=[],
            )
        claims = subtask.execution_result.claims if subtask.execution_result else []
        return ReviewResult(
            verdict="pass",
            issues=[],
            rework_targets=[],
            accepted_claims=[c.claim_id for c in claims],
            rejected_claims=[],
        )


def evidence_ids_of(state) -> set[str]:
    """从状态收集合法 evidence id（Tool Gateway 记录 + final_evidence）。"""
    ids: set[str] = set()
    for e in state.evidence:
        ids.add(e["id"] if isinstance(e, dict) else e.id)
    ids |= {e.id for e in state.final_evidence}
    return ids


def role_used_tool_calls(state, role: str, subtask_id: str) -> int:
    """按子任务统计工具调用次数。

    双口径（review sa_20260805_035741 should-fix）：优先按 subtask_id 精确归属
    （LLMResearcher 工具循环记录），无 subtask_id 的旧记录按 role
    （"researcher" 或 "researcher:<subtask_id>"）匹配。
    """
    full = f"{role}:{subtask_id}"
    total = 0
    for c in state.tool_calls:
        rec = c if isinstance(c, dict) else c.model_dump()
        if rec.get("subtask_id") is not None:
            if rec["subtask_id"] == subtask_id:
                total += 1
        elif rec.get("role") in (role, full):
            total += 1
    return total
