from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from app.windows_control.models import AccessibilityElement, Bounds, WindowInfo


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class CaptureScope(str, Enum):
    FULL_SCREEN = "full_screen"
    MONITOR = "monitor"
    ACTIVE_WINDOW = "active_window"
    WINDOW = "window"
    REGION = "region"


class ConfidenceBand(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class GroundingStatus(str, Enum):
    RESOLVED = "resolved"
    NEEDS_CLARIFICATION = "needs_clarification"
    REJECTED = "rejected"
    STALE = "stale"


class VisionMode(str, Enum):
    ACCESSIBILITY_ONLY = "accessibility_only"
    LOCAL_VISUAL = "local_visual"
    LOCAL_FUSION = "local_fusion"
    EXTERNAL_MULTIMODAL = "external_multimodal"


class MonitorInfo(BaseModel):
    monitor_id: str
    bounds: Bounds
    primary: bool = False
    scale_factor: float = Field(default=1.0, gt=0)


class CaptureMetadata(BaseModel):
    capture_id: str
    timestamp: str = Field(default_factory=utc_now)
    expires_at: str
    scope: CaptureScope
    monitor_id: str | None = None
    window_id: str | None = None
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    scale_factor: float = Field(default=1.0, gt=0)
    bounds: Bounds
    image_ref_ephemeral: str
    content_hash: str
    session_id: str
    window_hash: str | None = None
    ephemeral: bool = True


class PrivacyRedaction(BaseModel):
    redaction_id: str
    bounds: Bounds
    reason: str
    accessibility_element_id: str | None = None


class VisualElement(BaseModel):
    visual_element_id: str
    label: str = Field(default="", max_length=500)
    element_type: str = Field(default="unknown", max_length=100)
    text: str = Field(default="", max_length=1000)
    icon_hint: str = Field(default="", max_length=100)
    bounds: Bounds
    confidence: float = Field(ge=0, le=1)
    source: str
    accessibility_element_id: str | None = None
    parent_visual_element_id: str | None = None
    clickable_estimate: bool = False
    editable_estimate: bool = False
    sensitive: bool = False
    attributes: dict[str, Any] = Field(default_factory=dict)


class VisionObservation(BaseModel):
    vision_observation_id: str
    capture_id: str
    timestamp: str = Field(default_factory=utc_now)
    elements: list[VisualElement] = Field(default_factory=list)
    source: str = "local_deterministic_cv"
    summary: str = ""
    confidence: float = Field(default=0, ge=0, le=1)
    external_processing: bool = False
    provider: str | None = None
    model: str | None = None
    usage: dict[str, int | float | None] = Field(default_factory=dict)


class DesktopObservation(BaseModel):
    observation_id: str
    timestamp: str = Field(default_factory=utc_now)
    active_window: WindowInfo | None = None
    windows: list[WindowInfo] = Field(default_factory=list)
    screen_bounds: Bounds
    monitor_layout: list[MonitorInfo] = Field(default_factory=list)
    accessibility_elements: list[AccessibilityElement] = Field(default_factory=list)
    visual_elements: list[VisualElement] = Field(default_factory=list)
    focused_element: AccessibilityElement | None = None
    cursor_position: tuple[int, int] | None = None
    privacy_redactions: list[PrivacyRedaction] = Field(default_factory=list)
    source_modes: list[str] = Field(default_factory=list)
    capture_id: str
    capture_hash: str
    capture_expires_at: str
    capture_scope: CaptureScope
    capture_bounds: Bounds
    scale_factor: float = Field(default=1.0, gt=0)
    confidence: float = Field(default=0, ge=0, le=1)
    vision_mode: VisionMode
    untrusted_screen_content: bool = True


class GroundingCandidate(BaseModel):
    visual_element_id: str
    label: str
    bounds: Bounds
    score: float = Field(ge=0, le=1)
    source: str


class VisualGrounding(BaseModel):
    grounding_id: str
    observation_id: str
    capture_id: str
    target_description: str
    candidate_elements: list[GroundingCandidate] = Field(default_factory=list)
    selected_element: VisualElement | None = None
    selected_bounds: Bounds | None = None
    confidence: float = Field(default=0, ge=0, le=1)
    confidence_band: ConfidenceBand = ConfidenceBand.LOW
    reason_summary_safe: str = ""
    accessibility_match: bool = False
    requires_coordinate_fallback: bool = True
    status: GroundingStatus = GroundingStatus.REJECTED
    created_at: str = Field(default_factory=utc_now)
    clarification_prompt: str | None = None


class VisualActionResult(BaseModel):
    action_id: str
    grounding_id: str
    status: str
    attempts: int = Field(ge=0, le=2)
    verification: str
    before_observation_id: str
    after_observation_id: str | None = None
    change_score: float = Field(default=0, ge=0, le=1)
    used_accessibility: bool = False
    error_code: str | None = None


class VisionCapability(BaseModel):
    provider: str
    model: str
    supports_image_input: bool = False
    supports_multi_image: bool = False
    max_image_size: int | None = None
    supported_formats: list[str] = Field(default_factory=lambda: ["image/png"])
    local: bool = False
    verified: bool = False


class VisionSettings(BaseModel):
    route_provider: str | None = None
    route_model: str | None = None
    allow_external_processing: bool = False
    consent_acknowledged: bool = False
    max_dimension: int = Field(default=1600, ge=256, le=4096)
    compression_quality: int = Field(default=85, ge=40, le=95)
    auto_refresh: bool = False
    max_refresh_fps: float = Field(default=1.0, gt=0, le=1.0)


class ScreenAnswer(BaseModel):
    observation_id: str
    intent: str = "observe"
    answer: str
    vision_mode: VisionMode
    action_count: int = 0
    context_elements: int = 0
    untrusted_screen_content: bool = True
