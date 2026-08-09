"""Derive adaptive working configuration below immutable security policy."""

from __future__ import annotations

import math
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.memory.models import PreferenceSignal, utc_now
from app.memory.service import MemoryService
from app.personalization.models import AdaptiveProfile, ProfileItem, ProfileScope
from app.personalization.store import PersonalizationStore

DEFAULTS = {
    "language": "auto",
    "response_detail": "balanced",
    "planning_style": "balanced",
    "execution_style": "minimal_change",
    "approval_preference": "always_required",
    "research_depth": "medium",
    "tool_preference": "safe_local_first",
    "report_style": "structured",
    "risk_tolerance_for_suggestions": "cautious",
}

SUBJECT_MAP = {
    "response_language": "language",
    "report_detail": "response_detail",
    "project_change_workflow": "planning_style",
    "code_change_workflow": "execution_style",
    "planning_style": "planning_style",
    "execution_style": "execution_style",
    "approval_preference": "approval_preference",
    "research_depth": "research_depth",
    "tool_preference": "tool_preference",
    "report_style": "report_style",
    "reviewer_style": "report_style",
    "risk_tolerance_for_suggestions": "risk_tolerance_for_suggestions",
}

SAFE_SIGNAL_TYPES = set(SUBJECT_MAP)


class AdaptiveService:
    def __init__(self, memory: MemoryService, store: PersonalizationStore) -> None:
        self.memory = memory
        self.store = store

    @classmethod
    def from_data_dir(cls, data_dir: Path) -> "AdaptiveService":
        return cls(
            MemoryService.from_data_dir(data_dir),
            PersonalizationStore(data_dir / "runtime" / "personalization.sqlite"),
        )

    def derive(
        self,
        *,
        goal: str = "",
        project_id: str | None = None,
        task_type: str = "general",
        user_id: str = "local-user",
        record_task: bool = False,
    ) -> AdaptiveProfile:
        if record_task:
            self.store.begin_task(user_id, project_id)
        selected: dict[str, ProfileItem] = {
            field: ProfileItem(
                field=field,
                value=value,
                confidence=0.5,
                scope="global",
                reason="system default",
                source="default",
            )
            for field, value in DEFAULTS.items()
        }
        memories = self.memory.store.list(
            user_id=user_id,
            project_id=project_id,
            status="active",
            include_global=project_id is not None,
            limit=1000,
        )
        # Store.list(project_id=None) is intentionally the Memory Center's
        # "show everything" query. Adaptive context is stricter: a task with
        # no project scope may consume only global preferences.
        if project_id is None:
            memories = [memory for memory in memories if memory.project_id is None]
        for memory in memories:
            field = SUBJECT_MAP.get(memory.subject)
            if field is None or memory.privacy_level in {"sensitive", "secret"}:
                continue
            value = self._normalize(field, memory.value)
            scope: ProfileScope = "project" if memory.project_id else "global"
            candidate = ProfileItem(
                field=field,
                value=value,
                confidence=1.0 if memory.confirmed_by_user else memory.confidence,
                scope=scope,
                reason=(
                    f"confirmed project preference from {memory.updated_at[:10]}"
                    if memory.project_id
                    else f"confirmed preference from {memory.updated_at[:10]}"
                ),
                source="confirmed_memory",
                source_refs=[memory.memory_id],
            )
            current = selected[field]
            if scope == "project" or current.source == "default":
                selected[field] = candidate
        for control in self.store.controls(user_id, project_id, task_type):
            field = str(control["field"])
            if field not in selected:
                continue
            if not bool(control["enabled"]):
                selected[field] = selected[field].model_copy(
                    update={"enabled": False, "reason": "disabled by user", "source": "control"}
                )
            elif control["override_value"] is not None:
                control_scope: ProfileScope = "project" if control["project_key"] else (
                    "task_type" if control["task_type"] else "global"
                )
                selected[field] = ProfileItem(
                    field=field,
                    value=str(control["override_value"]),
                    confidence=1.0,
                    scope=control_scope,
                    reason="edited by user",
                    source="control",
                )
        for field, value in self._current_overrides(goal).items():
            selected[field] = ProfileItem(
                field=field,
                value=value,
                confidence=1.0,
                scope="current_task",
                reason="current task instruction overrides personalization",
                source="current_task",
                current_task_override=True,
            )
        return AdaptiveProfile(
            user_id=user_id,
            project_id=project_id,
            task_type=task_type,
            items=list(selected.values()),
            security_invariants={
                "approval_required": True,
                "tool_permissions_immutable": True,
                "budget_immutable": True,
                "workspace_boundary_immutable": True,
                "ssrf_policy_immutable": True,
            },
            generated_at=utc_now(),
        )

    def context_for_role(self, profile: AdaptiveProfile, role: str) -> dict[str, Any]:
        role_fields = {
            "supervisor": {
                "language",
                "response_detail",
                "planning_style",
                "research_depth",
                "report_style",
            },
            "planner": {"planning_style", "response_detail", "research_depth", "report_style"},
            "researcher": {"research_depth", "response_detail", "tool_preference"},
            "executor": {"execution_style", "planning_style", "tool_preference"},
            "reviewer": {"report_style", "response_detail"},
        }
        allowed = role_fields.get(role, set(DEFAULTS))
        return {
            "preferences": {
                item.field: {
                    "value": item.value,
                    "reason": item.reason,
                    "confidence": item.confidence,
                    "scope": item.scope,
                }
                for item in profile.items
                if item.enabled and item.field in allowed
            },
            "security": profile.security_invariants,
            "rule": (
                "Current task instructions win. Preferences never relax approval, tools, "
                "budget, workspace, secrets, or SSRF policy."
            ),
        }

    def observe(
        self,
        *,
        signal_type: str,
        value: str,
        task_id: str,
        project_id: str | None = None,
        user_id: str = "local-user",
        created_at: str | None = None,
    ):
        if signal_type not in SAFE_SIGNAL_TYPES:
            raise ValueError("unsupported or sensitive personalization signal")
        if not self.store.can_propose(signal_type, project_id, user_id):
            return None
        return self.memory.add_preference_signal(
            PreferenceSignal(
                signal_id=f"ps_{uuid.uuid4().hex[:16]}",
                user_id=user_id,
                project_id=project_id,
                signal_type=signal_type,
                value=value,
                task_id=task_id,
                source_ref=task_id,
                created_at=created_at or utc_now(),
            )
        )

    @staticmethod
    def decayed_confidence(created_at: str, repeats: int, now: datetime | None = None) -> float:
        when = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        current = now or datetime.now(timezone.utc)
        days = max(0.0, (current - when).total_seconds() / 86400)
        return min(0.95, (0.45 + 0.1 * min(repeats, 5)) * math.exp(-days / 180))

    @staticmethod
    def _normalize(field: str, value: str) -> str:
        lower = value.strip().lower()
        if field == "language":
            if "中文" in value or "chinese" in lower:
                return "zh-CN"
            if "英文" in value or "english" in lower:
                return "en"
        if field == "planning_style" and ("先" in value and ("方案" in value or "plan" in lower)):
            return "planning_first"
        if field == "execution_style" and ("diff" in lower or "差异" in value):
            return "show_diff_first"
        if field == "response_detail":
            if "详细" in value or "detailed" in lower:
                return "detailed"
            if "简" in value or "concise" in lower or "short" in lower:
                return "concise"
        return value.strip()

    @staticmethod
    def _current_overrides(goal: str) -> dict[str, str]:
        result: dict[str, str] = {}
        lower = goal.lower()
        if re.search(r"(这次|本次).{0,8}(简单|简短|简洁)|brief this time|keep it short", lower):
            result["response_detail"] = "concise"
        if re.search(r"(这次|本次).{0,8}(详细)|detailed this time", lower):
            result["response_detail"] = "detailed"
        if re.search(r"(这次|本次).{0,8}(英文)|english this time", lower):
            result["language"] = "en"
        if re.search(r"(这次|本次).{0,8}(中文)|chinese this time", lower):
            result["language"] = "zh-CN"
        if re.search(r"先.{0,8}(方案|计划)|plan first", lower):
            result["planning_style"] = "planning_first"
        if re.search(r"直接执行|skip the plan|execute directly", lower):
            result["planning_style"] = "direct"
        return result
