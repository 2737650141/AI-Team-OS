"""Deterministic product completion checks. A terminal status alone is not success."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.core.orchestration import TaskShape


@dataclass(frozen=True)
class CompletionDecision:
    complete: bool
    failure_code: str | None = None
    reasons: list[str] = field(default_factory=list)


class ProductCompletionValidator:
    def validate(self, state, shape: TaskShape) -> CompletionDecision:
        active = [item for item in state.subtasks if not item.superseded]
        if shape is TaskShape.DIRECT_RESPONSE:
            return CompletionDecision(True)
        reasons: list[str] = []
        results = [item.execution_result for item in active if item.execution_result is not None]
        if not results or not any((item.summary or "").strip() for item in results):
            reasons.append("result_nonempty")
        if shape is TaskShape.READ_ONLY_RESEARCH:
            claim_count = sum(len(item.claims) for item in results)
            if claim_count == 0:
                reasons.append("research_claims")
            requested = re.search(r"(?:找|对比|比较|研究)\s*([1-9])\s*个", state.user_goal)
            if requested and claim_count < int(requested.group(1)):
                reasons.append("requested_result_count")
            if not any(item.evidence_refs for item in results):
                reasons.append("evidence_coverage")
        elif shape is TaskShape.CODE_CHANGE:
            executor = [item for item in active if item.assigned_role == "executor"]
            if not executor:
                reasons.append("code_diff")
            for item in executor:
                metadata = item.execution_result.metadata if item.execution_result else {}
                if metadata.get("status") not in {"implemented", "implemented_replay"}:
                    reasons.append("code_diff")
                tests = metadata.get("test_report")
                if not isinstance(tests, dict) or tests.get("return_code") != 0:
                    reasons.append("tests")
                if not item.review_history or item.review_history[-1].status not in {
                    "PASS",
                    "PASS_WITH_NOTES",
                }:
                    reasons.append("review")
        elif shape is TaskShape.CODE_ANALYSIS:
            writes = [
                call
                for call in state.tool_calls
                if any(word in call.tool for word in ("write", "patch", "delete", "move"))
            ]
            if writes:
                reasons.append("unauthorized_write")
        elif shape is TaskShape.WINDOWS_ACTION:
            if not any((item.metadata or {}).get("verified") for item in results):
                reasons.append("action_verified")
        unique = list(dict.fromkeys(reasons))
        return CompletionDecision(
            not unique,
            None if not unique else "completion_invalid",
            unique,
        )
