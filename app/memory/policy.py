"""Deterministic governance for every memory write path."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.secrets import redact, scan_text
from app.memory.models import MemoryProposal

_EXTERNAL_SOURCES = {"task_result", "system_observation", "model_inference"}
_GOVERNED_TYPES = {"semantic_user", "procedural_preference"}
_SENSITIVE_TOPICS = {
    "health",
    "medical",
    "politics",
    "religion",
    "sexuality",
    "finance",
    "identity_number",
}


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    status: str
    reason: str
    safe_value: str


class MemoryPolicy:
    """Models may propose; only this deterministic policy permits persistence."""

    def evaluate(
        self, proposal: MemoryProposal, *, trusted_user_source: bool = False
    ) -> PolicyDecision:
        value = proposal.proposed_value
        if scan_text(value):
            return PolicyDecision(False, "rejected", "secret_detected", redact(value))
        if proposal.privacy_level == "secret":
            return PolicyDecision(False, "rejected", "secret_privacy_disallowed", "***")
        if proposal.privacy_level == "sensitive":
            return PolicyDecision(False, "quarantined", "sensitive_requires_explicit_workflow", "")
        lowered_tags = {tag.lower() for tag in proposal.tags}
        if lowered_tags & _SENSITIVE_TOPICS:
            return PolicyDecision(False, "quarantined", "sensitive_inference_disallowed", "")
        if proposal.source_type in _EXTERNAL_SOURCES and proposal.memory_type in _GOVERNED_TYPES:
            return PolicyDecision(
                False, "rejected", "external_content_cannot_define_user_preference", ""
            )
        if proposal.source_type == "explicit_user_statement" and not trusted_user_source:
            return PolicyDecision(False, "rejected", "untrusted_source_claimed_to_be_user", "")
        return PolicyDecision(True, "proposed", "confirmation_required", value)
