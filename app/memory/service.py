"""Governance, retrieval, task proposals, adaptation and trace orchestration."""

from __future__ import annotations

import math
import re
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.memory.models import (
    MemoryContextBudget,
    MemoryProposal,
    MemoryRecord,
    MemoryType,
    MemoryUsage,
    PreferenceSignal,
    PrivacyLevel,
    Retention,
    SourceType,
    utc_now,
)
from app.memory.policy import MemoryPolicy, PolicyDecision
from app.memory.store import MemoryStore

_ROLE_TYPES: dict[str, set[str]] = {
    "supervisor": {"semantic_user", "project", "procedural_preference", "episodic"},
    "planner": {"project", "procedural_preference", "semantic_user", "episodic"},
    "researcher": {"project", "procedural_preference"},
    "executor": {"project", "procedural_preference"},
    "reviewer": {"project", "procedural_preference", "semantic_user"},
}


class MemoryService:
    def __init__(self, store: MemoryStore, policy: MemoryPolicy | None = None) -> None:
        self.store = store
        self.policy = policy or MemoryPolicy()

    @classmethod
    def from_data_dir(cls, data_dir: Path) -> MemoryService:
        return cls(MemoryStore(data_dir / "runtime" / "memory" / "memory.sqlite"))

    def propose(
        self,
        *,
        memory_type: MemoryType,
        subject: str,
        predicate: str,
        value: str,
        reason: str,
        source_type: SourceType,
        source_ref: str,
        project_id: str | None = None,
        user_id: str = "local-user",
        confidence: float = 0.9,
        privacy_level: PrivacyLevel = "personal",
        confirmation_required: bool = True,
        tags: list[str] | None = None,
        retention: Retention = "manual",
        expires_at: str | None = None,
        trusted_user_source: bool = False,
    ) -> tuple[MemoryProposal | None, PolicyDecision]:
        proposal = MemoryProposal(
            proposal_id=f"mp_{uuid.uuid4().hex[:16]}",
            user_id=user_id,
            project_id=project_id,
            memory_type=memory_type,
            subject=subject.strip()[:200],
            predicate=predicate.strip()[:100],
            proposed_value=value.strip()[:4000],
            reason=reason.strip()[:1000],
            source_type=source_type,
            source_ref=source_ref.strip()[:500],
            confidence=max(0.0, min(confidence, 1.0)),
            privacy_level=privacy_level,
            confirmation_required=confirmation_required,
            created_at=utc_now(),
            tags=(tags or [])[:20],
            retention=retention,
            expires_at=expires_at,
        )
        decision = self.policy.evaluate(proposal, trusted_user_source=trusted_user_source)
        if not decision.allowed:
            # Never persist rejected content; caller receives only policy reason.
            return None, decision
        proposal.proposed_value = decision.safe_value
        self.store.create_proposal(proposal)
        return proposal, decision

    def confirm(self, proposal_id: str, edited_value: str | None = None) -> MemoryRecord:
        proposal = self.store.get_proposal(proposal_id)
        if proposal is None:
            raise KeyError(proposal_id)
        if edited_value is not None:
            check = proposal.model_copy(update={"proposed_value": edited_value})
            decision = self.policy.evaluate(check, trusted_user_source=True)
            if not decision.allowed:
                raise ValueError(decision.reason)
            edited_value = decision.safe_value
        return self.store.confirm_proposal(proposal_id, edited_value)

    def detect_explicit_proposals(
        self,
        text: str,
        *,
        run_id: str,
        project_id: str | None,
        user_id: str = "local-user",
    ) -> list[MemoryProposal]:
        memory_settings = self.store.get_settings(user_id)
        if not memory_settings.enabled:
            return []
        candidates: list[dict[str, Any]] = []
        lowered = text.lower()
        if re.search(r"(以后|优先|prefer).{0,12}(中文|chinese)", lowered, re.I):
            candidates.append(
                dict(
                    memory_type="procedural_preference",
                    subject="response_language",
                    predicate="prefer",
                    value="中文",
                    reason="用户明确要求后续优先使用中文",
                    tags=["language", "interaction_preference"],
                )
            )
        if re.search(r"(先|before).{0,18}(diff|差异)", lowered, re.I) or re.search(
            r"修改.{0,10}(前|之前).{0,8}(diff|差异)", lowered, re.I
        ):
            candidates.append(
                dict(
                    memory_type="procedural_preference",
                    subject="code_change_workflow",
                    predicate="require_before_change",
                    value="先展示 Diff，再修改代码",
                    reason="用户明确要求修改代码前先查看 Diff",
                    tags=["diff", "approval", "workflow"],
                )
            )
        if re.search(r"先.{0,8}(方案|plan).{0,8}(再|before).{0,8}(修改|change)", lowered, re.I):
            candidates.append(
                dict(
                    memory_type="procedural_preference",
                    subject="project_change_workflow",
                    predicate="require_before_change",
                    value="先给方案，再修改",
                    reason="用户明确要求该项目修改前先给方案",
                    tags=["plan", "approval", "workflow"],
                )
            )
        if re.search(r"(项目|project).{0,18}(使用|uses?).{0,8}langgraph", lowered, re.I):
            candidates.append(
                dict(
                    memory_type="project",
                    subject="orchestration_core",
                    predicate="uses",
                    value="LangGraph",
                    reason="用户明确确认项目编排核心",
                    tags=["architecture", "langgraph"],
                )
            )
        if re.search(r"(以后|prefer).{0,16}(详细|detailed)", lowered, re.I):
            candidates.append(
                dict(
                    memory_type="procedural_preference",
                    subject="report_detail",
                    predicate="prefer",
                    value="详细报告",
                    reason="用户明确要求后续报告更详细",
                    tags=["output", "detail"],
                )
            )
        if re.search(r"(以后|prefer).{0,16}(简短|concise|short)", lowered, re.I):
            candidates.append(
                dict(
                    memory_type="procedural_preference",
                    subject="report_detail",
                    predicate="prefer",
                    value="简短回复",
                    reason="用户明确要求后续回复更简短",
                    tags=["output", "concise"],
                )
            )
        proposals: list[MemoryProposal] = []
        for candidate in candidates:
            expires_at = None
            if memory_settings.retention == "fixed_ttl":
                expires_at = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
            proposal, _decision = self.propose(
                **candidate,
                source_type="explicit_user_statement",
                source_ref=run_id,
                project_id=project_id,
                user_id=user_id,
                confidence=0.98,
                privacy_level="personal",
                retention=memory_settings.retention,
                expires_at=expires_at,
                trusted_user_source=True,
            )
            if proposal is not None:
                low_risk = candidate["subject"] in {
                    "response_language",
                    "report_detail",
                    "orchestration_core",
                }
                if memory_settings.automatic_low_risk and low_risk:
                    self.confirm(proposal.proposal_id)
                else:
                    proposals.append(proposal)
        return proposals

    def retrieve(
        self,
        *,
        query: str,
        project_id: str | None,
        user_id: str = "local-user",
        role: str = "supervisor",
        budget: MemoryContextBudget | None = None,
    ) -> list[MemoryRecord]:
        settings = self.store.get_settings(user_id)
        if not settings.enabled:
            return []
        budget = budget or MemoryContextBudget()
        allowed_types = _ROLE_TYPES.get(role, _ROLE_TYPES["supervisor"])
        candidates = self.store.search(
            query,
            user_id=user_id,
            project_id=project_id,
            status="active",
            limit=max(budget.max_memories * 6, 50),
        )
        if not candidates:
            candidates = self.store.list(
                user_id=user_id,
                project_id=project_id,
                status="active",
                include_global=project_id is not None,
                limit=max(budget.max_memories * 6, 50),
            )
        candidates = [m for m in candidates if m.memory_type in allowed_types]
        candidates.sort(key=lambda m: self._score(m, project_id), reverse=True)
        selected: list[MemoryRecord] = []
        type_counts: Counter[str] = Counter()
        project_count = 0
        tokens = 0
        seen_facts: set[tuple[str, str]] = set()
        for memory in candidates:
            fact = (memory.subject, memory.predicate)
            if fact in seen_facts:
                continue
            token_count = self.estimate_tokens(memory.value)
            if len(selected) >= budget.max_memories or tokens + token_count > budget.max_tokens:
                continue
            if type_counts[memory.memory_type] >= budget.per_type_limit:
                continue
            if memory.project_id is not None and project_count >= budget.per_project_limit:
                continue
            selected.append(memory)
            seen_facts.add(fact)
            type_counts[memory.memory_type] += 1
            project_count += int(memory.project_id is not None)
            tokens += token_count
        return selected

    def resolve_refs_for_role(
        self,
        refs: list[dict[str, Any]],
        *,
        run_id: str,
        role: str,
        user_id: str = "local-user",
    ) -> list[dict[str, Any]]:
        if not self.store.get_settings(user_id).enabled:
            return []
        allowed_types = _ROLE_TYPES.get(role, _ROLE_TYPES["supervisor"])
        result: list[dict[str, Any]] = []
        for ref in refs:
            memory = self.store.get(str(ref.get("memory_id", "")))
            if (
                memory is None
                or memory.status != "active"
                or memory.version != int(ref.get("version", 0))
                or memory.memory_type not in allowed_types
            ):
                continue
            scope = f"project:{memory.project_id}" if memory.project_id else "global"
            reason = "project_scope_match" if memory.project_id else "global_preference_match"
            usage = MemoryUsage(
                usage_id=f"mu_{uuid.uuid4().hex[:16]}",
                run_id=run_id,
                memory_id=memory.memory_id,
                memory_version=memory.version,
                role=role,
                reason_selected=reason,
                scope=scope,
                token_count=self.estimate_tokens(memory.value),
                used_at=utc_now(),
            )
            self.store.record_usage(usage)
            result.append(
                {
                    "memory_id": memory.memory_id,
                    "version": memory.version,
                    "type": memory.memory_type,
                    "subject": memory.subject,
                    "predicate": memory.predicate,
                    "value": memory.value,
                    "scope": scope,
                    "source": memory.source_type,
                    "reason_selected": reason,
                }
            )
        return result

    def refs_for_task(
        self,
        goal: str,
        project_id: str | None,
        user_id: str = "local-user",
    ) -> list[dict[str, Any]]:
        memories = self.retrieve(
            query=goal,
            project_id=project_id,
            user_id=user_id,
            role="supervisor",
        )
        return [{"memory_id": m.memory_id, "version": m.version} for m in memories]

    def add_preference_signal(self, signal: PreferenceSignal) -> MemoryProposal | None:
        settings = self.store.get_settings(signal.user_id)
        if not settings.enabled or not settings.preference_detection:
            return None
        self.store.add_signal(signal)
        signals = self.store.signals(
            user_id=signal.user_id,
            signal_type=signal.signal_type,
            value=signal.value,
        )
        task_ids = {item.task_id for item in signals}
        if len(task_ids) < 3:
            return None
        timestamps = [self._timestamp(item.created_at) for item in signals]
        if max(timestamps) - min(timestamps) < 3600:
            return None
        existing = self.store.list_proposals(user_id=signal.user_id, status="proposed")
        if any(
            p.subject == signal.signal_type and p.proposed_value == signal.value for p in existing
        ):
            return None
        proposal, _ = self.propose(
            memory_type="procedural_preference",
            subject=signal.signal_type,
            predicate="prefer",
            value=signal.value,
            reason="多个任务中重复观察到同一交互偏好，等待用户确认",
            source_type="system_observation",
            source_ref=signal.source_ref,
            project_id=signal.project_id,
            user_id=signal.user_id,
            confidence=min(0.6 + 0.08 * len(task_ids), 0.9),
            privacy_level="personal",
            tags=["interaction_preference"],
            trusted_user_source=False,
        )
        # system_observation may not define preferences directly. Progressive detection is a
        # deterministic exception, represented as imported_profile for confirmation only.
        if proposal is None:
            proposal, _ = self.propose(
                memory_type="procedural_preference",
                subject=signal.signal_type,
                predicate="prefer",
                value=signal.value,
                reason="多个任务中重复观察到同一交互偏好，等待用户确认",
                source_type="imported_profile",
                source_ref=signal.source_ref,
                project_id=signal.project_id,
                user_id=signal.user_id,
                confidence=min(0.6 + 0.08 * len(task_ids), 0.9),
                privacy_level="personal",
                tags=["interaction_preference"],
            )
        return proposal

    @staticmethod
    def estimate_tokens(text: str) -> int:
        return max(1, math.ceil(len(text) / 4))

    @staticmethod
    def _score(memory: MemoryRecord, project_id: str | None) -> float:
        scope = 3.0 if project_id and memory.project_id == project_id else 1.5
        confirmation = 1.0 if memory.confirmed_by_user else 0.0
        freshness = 0.0
        try:
            age_days = max(
                0.0,
                (
                    datetime.now(timezone.utc) - datetime.fromisoformat(memory.updated_at)
                ).total_seconds()
                / 86400,
            )
            freshness = 1.0 / (1.0 + age_days / 30.0)
        except ValueError:
            pass
        priority = 1.5 if memory.memory_type == "project" else 1.0
        if "approval" in memory.tags or "security" in memory.tags:
            priority += 1.0
        return scope + confirmation + freshness + priority + memory.confidence

    @staticmethod
    def _timestamp(value: str) -> float:
        return datetime.fromisoformat(value).timestamp()
