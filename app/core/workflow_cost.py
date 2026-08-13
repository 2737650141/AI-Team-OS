"""Real-time model-call governance for bounded workflows."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum
from threading import Lock


class CostDecision(str, Enum):
    ALLOW = "allow"
    WARNING = "warning"
    RECOVERY = "recovery"
    STOP = "stop"


@dataclass(frozen=True)
class CostAssessment:
    decision: CostDecision
    calls_used: int
    role_calls: int
    estimated_remaining_calls: int
    reason: str


class WorkflowCostGovernor:
    STANDARD_ROLE_LIMITS = {
        "supervisor": 2,
        "planner": 2,
        "researcher": 4,
        "executor": 3,
        "reviewer": 2,
    }
    SOFT_THRESHOLD = 12
    RECOVERY_THRESHOLD = 16
    HARD_THRESHOLD = 20

    def __init__(self, complexity: str = "standard", hard_limit: int | None = None) -> None:
        self.complexity = complexity
        self.hard_limit = hard_limit
        self._role_calls: Counter[str] = Counter()
        self._lock = Lock()
        self._reserved_total = 0

    @property
    def role_usage(self) -> dict[str, int]:
        with self._lock:
            return dict(self._role_calls)

    def assess(
        self, role: str, calls_used: int, estimated_remaining_calls: int = 1
    ) -> CostAssessment:
        role_calls = self._role_calls[role]
        hard = self.hard_limit or (32 if self.complexity == "complex" else self.HARD_THRESHOLD)
        if calls_used >= hard:
            return CostAssessment(
                CostDecision.STOP,
                calls_used,
                role_calls,
                0,
                f"hard model-call limit {hard} reached",
            )
        if self.complexity != "complex":
            limit = self.STANDARD_ROLE_LIMITS.get(role)
            if limit is not None and role_calls >= limit:
                return CostAssessment(
                    CostDecision.RECOVERY,
                    calls_used,
                    role_calls,
                    0,
                    f"role call limit reached: {role}={limit}",
                )
            if calls_used >= self.RECOVERY_THRESHOLD:
                return CostAssessment(
                    CostDecision.RECOVERY,
                    calls_used,
                    role_calls,
                    max(0, hard - calls_used),
                    "reuse evidence, skip optional work, or return a useful partial result",
                )
            if calls_used >= self.SOFT_THRESHOLD:
                return CostAssessment(
                    CostDecision.WARNING,
                    calls_used,
                    role_calls,
                    max(0, hard - calls_used),
                    "workflow is above the normal 12-call target",
                )
        return CostAssessment(
            CostDecision.ALLOW,
            calls_used,
            role_calls,
            max(0, hard - calls_used),
            "within workflow budget",
        )

    def record(self, role: str) -> None:
        with self._lock:
            self._role_calls[role] += 1

    def assess_and_reserve(
        self, role: str, calls_used: int, estimated_remaining_calls: int = 1
    ) -> CostAssessment:
        """Atomically enforce role limits for parallel LangGraph branches."""
        with self._lock:
            effective_calls = max(calls_used, self._reserved_total)
            assessment = self.assess(role, effective_calls, estimated_remaining_calls)
            if assessment.decision in {CostDecision.ALLOW, CostDecision.WARNING}:
                self._role_calls[role] += 1
                self._reserved_total += 1
            return assessment
