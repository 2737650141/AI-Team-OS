"""Typed contracts for governed long-term memory."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

MemoryType = Literal[
    "working",
    "episodic",
    "semantic_user",
    "project",
    "procedural_preference",
]
MemoryStatus = Literal[
    "proposed",
    "confirmed",
    "active",
    "rejected",
    "superseded",
    "expired",
    "forgotten",
    "quarantined",
]
PrivacyLevel = Literal["public", "personal", "sensitive", "secret"]
SourceType = Literal[
    "explicit_user_statement",
    "user_confirmation",
    "task_result",
    "approval_decision",
    "system_observation",
    "imported_profile",
    "model_inference",
]
Retention = Literal["permanent", "project_lifetime", "fixed_ttl", "task_only", "manual"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MemoryRecord(BaseModel):
    memory_id: str
    user_id: str = "local-user"
    project_id: str | None = None
    memory_type: MemoryType
    subject: str
    predicate: str
    value: str
    normalized_value: str
    confidence: float = Field(ge=0.0, le=1.0)
    status: MemoryStatus
    privacy_level: PrivacyLevel
    source_type: SourceType
    source_ref: str
    created_at: str
    updated_at: str
    last_used_at: str | None = None
    expires_at: str | None = None
    supersedes: str | None = None
    superseded_by: str | None = None
    confirmation_required: bool = True
    confirmed_by_user: bool = False
    version: int = Field(default=1, ge=1)
    content_hash: str
    tags: list[str] = Field(default_factory=list)
    retention: Retention = "manual"


class MemoryProposal(BaseModel):
    proposal_id: str
    user_id: str = "local-user"
    project_id: str | None = None
    memory_type: MemoryType
    subject: str
    predicate: str
    proposed_value: str
    reason: str
    source_type: SourceType
    source_ref: str
    confidence: float = Field(ge=0.0, le=1.0)
    privacy_level: PrivacyLevel
    confirmation_required: bool = True
    created_at: str
    status: MemoryStatus = "proposed"
    tags: list[str] = Field(default_factory=list)
    retention: Retention = "manual"
    expires_at: str | None = None


class MemoryConfirmationRequest(BaseModel):
    confirmation_id: str
    proposal_id: str
    action: Literal["confirm", "reject", "edit_confirm"]
    edited_value: str | None = None
    created_at: str


class PreferenceSignal(BaseModel):
    signal_id: str
    user_id: str = "local-user"
    project_id: str | None = None
    signal_type: str
    value: str
    task_id: str
    source_ref: str
    created_at: str = Field(default_factory=utc_now)


class MemoryContextBudget(BaseModel):
    max_memories: int = Field(default=12, ge=1, le=100)
    max_tokens: int = Field(default=1200, ge=100, le=10_000)
    per_type_limit: int = Field(default=5, ge=1, le=50)
    per_project_limit: int = Field(default=8, ge=1, le=100)


class MemorySettings(BaseModel):
    enabled: bool = True
    automatic_low_risk: bool = False
    preference_detection: bool = True
    retention: Retention = "manual"


class MemoryUsage(BaseModel):
    usage_id: str
    run_id: str
    memory_id: str
    memory_version: int
    role: str
    reason_selected: str
    scope: str
    token_count: int
    used_at: str


class MemoryHealth(BaseModel):
    schema_version: int
    integrity: str
    fts5: bool
    memories: int
    pending: int
