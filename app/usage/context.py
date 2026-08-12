from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any

from pydantic import BaseModel, Field

from app.usage.models import ContextStatus, utc_now


class ContextPolicy(BaseModel):
    compression_threshold: float = Field(default=0.8, gt=0, le=1)
    role_thresholds: dict[str, float] = Field(default_factory=dict)

    def threshold_for(self, role: str) -> float:
        return self.role_thresholds.get(role, self.compression_threshold)

    def status(self, current: int | None, limit: int | None, role: str = "") -> ContextStatus:
        if current is None or limit is None or limit <= 0:
            return ContextStatus.UNKNOWN
        ratio = current / limit
        threshold = self.threshold_for(role)
        if ratio >= 1:
            return ContextStatus.COMPACTION_REQUIRED
        if ratio >= threshold:
            return ContextStatus.NEAR_COMPACTION
        if ratio >= 0.6:
            return ContextStatus.MODERATE
        return ContextStatus.AMPLE


class ContextCheckpoint(BaseModel):
    checkpoint_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    task_id: str
    run_id: str | None = None
    user_goal: str = ""
    constraints: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    current_task: str = ""
    open_issues: list[str] = Field(default_factory=list)
    important_ids: list[str] = Field(default_factory=list)
    relevant_memory_refs: list[str] = Field(default_factory=list)
    files_being_edited: list[str] = Field(default_factory=list)
    test_failures: list[str] = Field(default_factory=list)
    reviewer_requirements: list[str] = Field(default_factory=list)
    approval_state: str = ""
    optional_summary: str | None = None
    created_at: str = Field(default_factory=utc_now)


class ContextCompactor:
    """Deterministic critical-state checkpoint plus optional bounded summary.

    The persisted checkpoint never contains raw message history. The in-memory compacted
    prompt uses only explicit critical fields supplied by the orchestrator.
    """

    def __init__(self, policy: ContextPolicy | None = None) -> None:
        self.policy = policy or ContextPolicy()

    def compact(
        self,
        *,
        task_id: str,
        run_id: str | None,
        role: str,
        model: str,
        current_tokens: int,
        context_limit: int,
        critical: dict[str, Any],
    ) -> tuple[ContextCheckpoint, dict[str, Any]]:
        started = time.perf_counter()
        allowed = set(ContextCheckpoint.model_fields) - {
            "checkpoint_id",
            "task_id",
            "run_id",
            "created_at",
        }
        safe_critical = {key: value for key, value in critical.items() if key in allowed}
        checkpoint = ContextCheckpoint(task_id=task_id, run_id=run_id, **safe_critical)
        serialized = json.dumps(checkpoint.model_dump(), ensure_ascii=False, sort_keys=True)
        # Used only for transparent before/after observability; never presented as reported usage.
        after = max(1, len(serialized.encode("utf-8")) // 4)
        return checkpoint, {
            "triggered": True,
            "before": current_tokens,
            "after": after,
            "freed": max(0, current_tokens - after),
            "role": role,
            "model": model,
            "duration_ms": max(1, int((time.perf_counter() - started) * 1000)),
            "checkpoint_hash": hashlib.sha256(serialized.encode()).hexdigest(),
        }
