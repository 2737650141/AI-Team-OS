from __future__ import annotations

from app.desktop_vision.capture import CaptureError, ScreenCaptureService
from app.desktop_vision.models import (
    ConfidenceBand,
    DesktopObservation,
    GroundingStatus,
    VisualGrounding,
)
from app.desktop_vision.privacy import ScreenPrivacyFilter
from app.windows_control.backend import AutomationError, WindowsAutomationBackend
from app.windows_control.models import ActionRisk, SessionCapability
from app.windows_control.session import DeviceSessionManager, SessionError


class VisualValidationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class VisualActionValidator:
    """Final governance check before any grounding reaches WindowsActionGateway."""

    def __init__(
        self,
        sessions: DeviceSessionManager,
        backend: WindowsAutomationBackend,
        captures: ScreenCaptureService,
        privacy: ScreenPrivacyFilter,
    ) -> None:
        self.sessions = sessions
        self.backend = backend
        self.captures = captures
        self.privacy = privacy

    def validate(
        self,
        grounding: VisualGrounding,
        observation: DesktopObservation,
        *,
        approved: bool = False,
    ) -> ActionRisk:
        try:
            session = self.sessions.require_active("windows_click_element")
        except SessionError as exc:
            raise VisualValidationError(exc.code, str(exc)) from exc
        if session.capability is SessionCapability.OBSERVE_ONLY:
            raise VisualValidationError("permission_denied", "Observe-only sessions cannot act")
        if grounding.status is not GroundingStatus.RESOLVED or grounding.selected_element is None:
            raise VisualValidationError("grounding_unresolved", "Visual target is not resolved")
        if grounding.observation_id != observation.observation_id:
            raise VisualValidationError("observation_mismatch", "Grounding belongs to another view")
        if grounding.confidence_band is ConfidenceBand.LOW:
            raise VisualValidationError(
                "low_confidence", "Low-confidence visual targets cannot act"
            )
        try:
            metadata = self.captures.metadata(grounding.capture_id, require_latest=True)
        except CaptureError as exc:
            raise VisualValidationError(exc.code, str(exc)) from exc
        if metadata.session_id != session.session_id:
            raise VisualValidationError("session_mismatch", "Capture belongs to another session")
        current_scale = self.captures.current_scale_factor(metadata.window_id)
        if abs(current_scale - metadata.scale_factor) > 0.01:
            raise VisualValidationError("dpi_mismatch", "Display scaling changed after capture")
        target = grounding.selected_element
        current = self.backend.get_active_window()
        if metadata.window_id:
            if current is None or current.window_id != metadata.window_id:
                raise VisualValidationError("window_mismatch", "Target window is no longer active")
            try:
                current_info = self.backend.get_window_info(metadata.window_id)
            except AutomationError as exc:
                raise VisualValidationError("window_mismatch", "Target window disappeared") from exc
            if current_info.bounds != metadata.bounds:
                raise VisualValidationError("resolution_mismatch", "Window dimensions changed")
            if metadata.window_hash != current_info.window_hash:
                raise VisualValidationError("window_changed", "Target window changed")
        latest_target = next(
            (
                item
                for item in observation.visual_elements
                if item.visual_element_id == target.visual_element_id
            ),
            None,
        )
        if latest_target is None or latest_target.bounds != grounding.selected_bounds:
            raise VisualValidationError(
                "target_moved", "Target no longer exists at grounded bounds"
            )
        if self.privacy.target_is_sensitive(target, observation.privacy_redactions):
            raise VisualValidationError(
                "sensitive_target_forbidden", "Sensitive targets are forbidden"
            )
        risk = ActionRisk.MEDIUM if grounding.accessibility_match else ActionRisk.HIGH
        if grounding.confidence_band is ConfidenceBand.MEDIUM:
            risk = ActionRisk.HIGH
        if session.capability is SessionCapability.ASK_EVERY_ACTION or risk is ActionRisk.HIGH:
            if not approved:
                raise VisualValidationError("approval_required", "Visual target requires approval")
        return risk
