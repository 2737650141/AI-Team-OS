"""Typed contracts for adaptive personalization."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ProfileScope = Literal["global", "project", "task_type", "current_task"]


class ProfileItem(BaseModel):
    field: str
    value: str
    confidence: float = Field(ge=0.0, le=1.0)
    scope: ProfileScope
    reason: str
    source: str
    source_refs: list[str] = Field(default_factory=list)
    enabled: bool = True
    current_task_override: bool = False


class AdaptiveProfile(BaseModel):
    user_id: str = "local-user"
    project_id: str | None = None
    task_type: str = "general"
    items: list[ProfileItem] = Field(default_factory=list)
    security_invariants: dict[str, Any] = Field(default_factory=dict)
    generated_at: str

    def values(self) -> dict[str, str]:
        return {item.field: item.value for item in self.items if item.enabled}
