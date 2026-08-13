"""Deterministic tool-call normalization and bounded argument repair."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ALIASES = {
    "q": "query",
    "repository": "repo",
    "repository_name": "repo",
    "name": "repo",
}


@dataclass(frozen=True)
class ToolArgumentPreparation:
    args: dict[str, Any]
    missing: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    normalized: dict[str, str] = field(default_factory=dict)
    deterministic_fills: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.missing


class ToolCallRepairLayer:
    PER_TOOL_REPAIR_LIMIT = 1
    RESEARCHER_REPAIR_LIMIT = 2

    @staticmethod
    def prepare(
        args: dict[str, Any],
        allowed: set[str],
        required: set[str],
        recent_entities: dict[str, list[str]] | None = None,
    ) -> ToolArgumentPreparation:
        source = dict(args or {})
        normalized: dict[str, str] = {}
        for old, new in ALIASES.items():
            if old in source and new in allowed and new not in source:
                source[new] = source.pop(old)
                normalized[old] = new
        removed = sorted(key for key in source if key not in allowed)
        filtered = {key: value for key, value in source.items() if key in allowed}
        fills: dict[str, Any] = {}
        entities = recent_entities or {}
        for key in sorted(required - set(filtered)):
            candidates = list(dict.fromkeys(entities.get(key, [])))
            if len(candidates) == 1:
                filtered[key] = candidates[0]
                fills[key] = candidates[0]
        missing = sorted(required - set(filtered))
        return ToolArgumentPreparation(filtered, missing, removed, normalized, fills)
