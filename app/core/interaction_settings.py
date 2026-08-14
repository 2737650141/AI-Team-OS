"""Explicit UX preferences, separate from security PermissionMode."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel


class InteractionSettings(BaseModel):
    mode: Literal["normal", "minimal_interruption"] = "normal"
    notify_completed: bool = True
    notify_approval: bool = True
    notify_failed: bool = True
    changed_at: str = ""


class InteractionSettingsStore:
    def __init__(self, data_dir: Path):
        self.path = data_dir / "runtime" / "interaction_settings.json"

    def get(self) -> InteractionSettings:
        if not self.path.exists():
            return InteractionSettings()
        try:
            return InteractionSettings.model_validate_json(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return InteractionSettings()

    def save(self, value: InteractionSettings) -> InteractionSettings:
        value = value.model_copy(
            update={"changed_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(value.model_dump_json(indent=2), encoding="utf-8")
        temp.replace(self.path)
        return value
