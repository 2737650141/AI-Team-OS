from __future__ import annotations

import ctypes
import uuid
from ctypes import wintypes

from app.desktop_vision.capture import ScreenCaptureService
from app.desktop_vision.fusion import ObservationFusion
from app.desktop_vision.local_cv import LocalVisualAnalyzer
from app.desktop_vision.models import (
    CaptureScope,
    DesktopObservation,
    PrivacyRedaction,
    VisionMode,
    VisionObservation,
    VisualElement,
)
from app.desktop_vision.privacy import ScreenPrivacyFilter
from app.desktop_vision.provider import VisionCapabilityRegistry, VisionPolicyError
from app.windows_control.backend import AutomationError, WindowsAutomationBackend
from app.windows_control.models import AccessibilityElement, Bounds


class AccessibilityObserver:
    """Normalizes UIA metadata and never reads secure values."""

    MAX_VISIBLE_ELEMENTS = 300

    def __init__(self, backend: WindowsAutomationBackend) -> None:
        self.backend = backend

    def observe(self, window_id: str | None) -> list[AccessibilityElement]:
        if not window_id:
            return []
        try:
            elements = self.backend.accessibility_tree(window_id)
        except AutomationError:
            return []
        return [
            item
            for item in elements
            if item.bounds is not None
            and item.bounds.width > 0
            and item.bounds.height > 0
        ][: self.MAX_VISIBLE_ELEMENTS]


class DesktopObserver:
    """Creates the unified DesktopObservation from local, governed sources."""

    MAX_EXTERNAL_ELEMENTS = 120

    def __init__(
        self,
        backend: WindowsAutomationBackend,
        captures: ScreenCaptureService,
        capabilities: VisionCapabilityRegistry,
        *,
        accessibility: AccessibilityObserver | None = None,
        local_visual: LocalVisualAnalyzer | None = None,
        privacy: ScreenPrivacyFilter | None = None,
        fusion: ObservationFusion | None = None,
    ) -> None:
        self.backend = backend
        self.captures = captures
        self.capabilities = capabilities
        self.accessibility = accessibility or AccessibilityObserver(backend)
        self.local_visual = local_visual or LocalVisualAnalyzer()
        self.privacy = privacy or ScreenPrivacyFilter()
        self.fusion = fusion or ObservationFusion()

    def observe(
        self,
        *,
        session_id: str,
        scope: CaptureScope = CaptureScope.ACTIVE_WINDOW,
        monitor_id: str | None = None,
        window_id: str | None = None,
        region: Bounds | None = None,
        external: bool = False,
        prompt: str = "Describe visible layout and controls",
    ) -> DesktopObservation:
        active = self.backend.get_active_window()
        windows = self.backend.list_windows()
        capture = self._capture(
            session_id=session_id,
            scope=scope,
            active_window_id=active.window_id if active else None,
            monitor_id=monitor_id,
            window_id=window_id,
            region=region,
        )
        target_window_id = capture.window_id or (active.window_id if active else None)
        accessibility = self.accessibility.observe(target_window_id)
        image = self.captures.image(capture.capture_id, require_latest=True)
        local = self.local_visual.analyze(image, capture)
        redactions = self.privacy.detect(accessibility, capture)
        visual_observation = local
        source_modes = ["screen_capture", "local_deterministic_cv"]
        mode = VisionMode.LOCAL_VISUAL
        if accessibility:
            source_modes.append("accessibility")
            mode = VisionMode.LOCAL_FUSION
        if external:
            adapter, capability = self.capabilities.external_adapter()
            redacted = self.privacy.apply(image, capture, redactions)
            redacted.thumbnail(
                (self.capabilities.settings.max_dimension,) * 2,
            )
            try:
                external_observation = adapter.analyze_screen(redacted, capture, prompt=prompt)
            except Exception as exc:
                raise VisionPolicyError(
                    "vision_provider_failed", "External vision provider failed safely"
                ) from exc
            external_observation.external_processing = True
            external_observation.provider = capability.provider
            external_observation.model = capability.model
            external_elements = self._sanitize_external_elements(
                external_observation.elements,
                capture.bounds,
                redactions,
                capability.provider,
            )
            visual_observation = VisionObservation(
                vision_observation_id=external_observation.vision_observation_id,
                capture_id=capture.capture_id,
                elements=[*local.elements, *external_elements],
                source="local_and_external",
                summary=external_observation.summary,
                confidence=max(local.confidence, external_observation.confidence),
                external_processing=True,
                provider=capability.provider,
                model=capability.model,
                usage=external_observation.usage,
            )
            source_modes.append("external_multimodal")
            mode = VisionMode.EXTERNAL_MULTIMODAL
        visual_elements = self.fusion.fuse(accessibility, visual_observation)
        if not visual_elements and accessibility:
            mode = VisionMode.ACCESSIBILITY_ONLY
        layout = self.captures.monitor_layout()
        screen_bounds = self._screen_bounds(layout) if layout else capture.bounds
        confidence = max((item.confidence for item in visual_elements), default=0.7)
        return DesktopObservation(
            observation_id=f"obs_{uuid.uuid4().hex[:20]}",
            active_window=active,
            windows=windows,
            screen_bounds=screen_bounds,
            monitor_layout=layout,
            accessibility_elements=accessibility,
            visual_elements=visual_elements,
            focused_element=None,
            cursor_position=self._cursor_position(),
            privacy_redactions=redactions,
            source_modes=source_modes,
            capture_id=capture.capture_id,
            capture_hash=capture.content_hash,
            capture_expires_at=capture.expires_at,
            capture_scope=capture.scope,
            capture_bounds=capture.bounds,
            scale_factor=capture.scale_factor,
            confidence=confidence,
            vision_mode=mode,
        )

    def _capture(
        self,
        *,
        session_id: str,
        scope: CaptureScope,
        active_window_id: str | None,
        monitor_id: str | None,
        window_id: str | None,
        region: Bounds | None,
    ):
        if scope is CaptureScope.FULL_SCREEN:
            return self.captures.capture_full_screen(session_id=session_id)
        if scope is CaptureScope.MONITOR:
            if not monitor_id:
                raise ValueError("monitor_id is required")
            return self.captures.capture_monitor(monitor_id, session_id=session_id)
        if scope is CaptureScope.ACTIVE_WINDOW:
            return self.captures.capture_active_window(session_id=session_id)
        if scope is CaptureScope.WINDOW:
            target = window_id or active_window_id
            if not target:
                raise ValueError("window_id is required")
            return self.captures.capture_window(target, session_id=session_id)
        if region is None:
            raise ValueError("region is required")
        return self.captures.capture_region(
            region, session_id=session_id, window_id=window_id or active_window_id
        )

    @staticmethod
    def _screen_bounds(layout) -> Bounds:
        return Bounds(
            left=min(item.bounds.left for item in layout),
            top=min(item.bounds.top for item in layout),
            right=max(item.bounds.right for item in layout),
            bottom=max(item.bounds.bottom for item in layout),
        )

    @staticmethod
    def _cursor_position() -> tuple[int, int] | None:
        try:
            point = wintypes.POINT()
            if ctypes.windll.user32.GetCursorPos(ctypes.byref(point)):
                return int(point.x), int(point.y)
        except Exception:
            return None
        return None

    def _sanitize_external_elements(
        self,
        elements: list[VisualElement],
        capture_bounds: Bounds,
        redactions: list[PrivacyRedaction],
        provider: str,
    ) -> list[VisualElement]:
        """Treat provider output as untrusted pixels, never as an Accessibility identity."""
        safe: list[VisualElement] = []
        for item in elements[: self.MAX_EXTERNAL_ELEMENTS]:
            if not self._contains(capture_bounds, item.bounds):
                continue
            safe.append(
                item.model_copy(
                    deep=True,
                    update={
                        "source": "external_multimodal",
                        "accessibility_element_id": None,
                        "sensitive": self.privacy.target_is_sensitive(item, redactions),
                        "attributes": {
                            "screen_content_trust": "untrusted",
                            "provider": provider[:100],
                        },
                    },
                )
            )
        return safe

    @staticmethod
    def _contains(outer: Bounds, inner: Bounds) -> bool:
        return (
            outer.left <= inner.left < inner.right <= outer.right
            and outer.top <= inner.top < inner.bottom <= outer.bottom
        )
