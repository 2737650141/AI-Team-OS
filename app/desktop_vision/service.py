from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from app.core.events import init as events_init
from app.desktop_vision.capture import CaptureError, ScreenCaptureService
from app.desktop_vision.change import ScreenChangeDetector
from app.desktop_vision.context import ScreenContextBuilder
from app.desktop_vision.grounding import GroundingResolver
from app.desktop_vision.models import (
    CaptureScope,
    DesktopObservation,
    GroundingStatus,
    ScreenAnswer,
    VisualActionResult,
    VisualGrounding,
)
from app.desktop_vision.observer import DesktopObserver
from app.desktop_vision.privacy import ScreenPrivacyFilter
from app.desktop_vision.provider import VisionCapabilityRegistry
from app.desktop_vision.validator import VisualActionValidator, VisualValidationError
from app.windows_control.backend import WindowsAutomationBackend
from app.windows_control.gateway import ActionError, WindowsActionGateway
from app.windows_control.models import ActionStep, Bounds
from app.windows_control.session import DeviceSessionManager


class VisualDesktopError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class VisualDesktopService:
    """Session-scoped visual intelligence; all mutations still flow through the M5-A gateway."""

    MAX_HISTORY = 30

    def __init__(
        self,
        data_dir: Path,
        sessions: DeviceSessionManager,
        backend: WindowsAutomationBackend,
        gateway: WindowsActionGateway,
    ) -> None:
        self.sessions = sessions
        self.backend = backend
        self.gateway = gateway
        self.captures = ScreenCaptureService(backend)
        self.capabilities = VisionCapabilityRegistry()
        self.privacy = ScreenPrivacyFilter()
        self.observer = DesktopObserver(
            backend,
            self.captures,
            self.capabilities,
            privacy=self.privacy,
        )
        self.resolver = GroundingResolver()
        self.validator = VisualActionValidator(sessions, backend, self.captures, self.privacy)
        self.change_detector = ScreenChangeDetector()
        self.context_builder = ScreenContextBuilder()
        self._observations: dict[str, DesktopObservation] = {}
        self._groundings: dict[str, VisualGrounding] = {}
        self._actions: list[VisualActionResult] = []
        self._events = events_init(data_dir)

    def observe(
        self,
        *,
        scope: CaptureScope = CaptureScope.ACTIVE_WINDOW,
        monitor_id: str | None = None,
        window_id: str | None = None,
        region: Bounds | None = None,
        external: bool = False,
        prompt: str = "Describe visible layout and controls",
    ) -> DesktopObservation:
        session = self.sessions.require_active("windows_capture_screen")
        self._emit("vision_analysis_started", {"scope": scope.value, "external": external})
        observation = self.observer.observe(
            session_id=session.session_id,
            scope=scope,
            monitor_id=monitor_id,
            window_id=window_id,
            region=region,
            external=external,
            prompt=prompt,
        )
        self._observations[observation.observation_id] = observation
        self._trim()
        self._emit(
            "screen_observed",
            {
                "observation_id": observation.observation_id,
                "capture_id": observation.capture_id,
                "capture_hash": observation.capture_hash,
                "width": observation.screen_bounds.width,
                "height": observation.screen_bounds.height,
                "window_id": observation.active_window.window_id
                if observation.active_window
                else None,
                "vision_mode": observation.vision_mode.value,
                "redactions": len(observation.privacy_redactions),
            },
        )
        self._emit(
            "vision_analysis_completed",
            {
                "observation_id": observation.observation_id,
                "elements": len(observation.visual_elements),
                "confidence": observation.confidence,
                "external": external,
            },
        )
        return observation.model_copy(deep=True)

    def ground(self, observation_id: str, target: str) -> VisualGrounding:
        observation = self._observation(observation_id)
        try:
            self.captures.metadata(observation.capture_id, require_latest=True)
        except CaptureError as exc:
            raise VisualDesktopError(exc.code, str(exc)) from exc
        grounding = self.resolver.resolve(observation, self._resolve_reference(target))
        self._groundings[grounding.grounding_id] = grounding
        self._emit(
            "grounding_created"
            if grounding.status is GroundingStatus.RESOLVED
            else "grounding_rejected",
            {
                "grounding_id": grounding.grounding_id,
                "observation_id": observation_id,
                "status": grounding.status.value,
                "confidence": grounding.confidence,
                "candidate_count": len(grounding.candidate_elements),
                "accessibility_match": grounding.accessibility_match,
            },
        )
        return grounding.model_copy(deep=True)

    def ask(self, question: str, *, observation_id: str | None = None) -> ScreenAnswer:
        if observation_id:
            observation = self._observation(observation_id)
        else:
            observation = self.observe()
        # Build the marked USER_REQUEST / UNTRUSTED_SCREEN_OBSERVATION boundary even though
        # the current deterministic answer path does not invoke a model.
        self.context_builder.build(observation, question)
        return self.context_builder.answer(observation, question)

    def act(self, grounding_id: str, *, approved: bool = False) -> VisualActionResult:
        grounding = self._groundings.get(grounding_id)
        if grounding is None:
            raise VisualDesktopError("grounding_not_found", "Grounding does not exist")
        observation = self._observation(grounding.observation_id)
        self._emit(
            "visual_action_started",
            {
                "grounding_id": grounding_id,
                "confidence": grounding.confidence,
                "accessibility_match": grounding.accessibility_match,
            },
        )
        try:
            risk = self.validator.validate(grounding, observation, approved=approved)
        except VisualValidationError as exc:
            self._emit("visual_action_failed", {"grounding_id": grounding_id, "code": exc.code})
            raise VisualDesktopError(exc.code, str(exc)) from exc
        before_image = self.captures.image(observation.capture_id, require_latest=True)
        current_grounding = grounding
        current_observation = observation
        last_after: DesktopObservation | None = None
        last_score = 0.0
        for attempt in range(1, 3):
            # A new capture invalidates old coordinates. Re-ground against the fresh view.
            fresh = self.observe(
                scope=observation.capture_scope,
                window_id=(
                    observation.active_window.window_id if observation.active_window else None
                ),
            )
            current_grounding = self.resolver.resolve(fresh, grounding.target_description)
            if current_grounding.status is not GroundingStatus.RESOLVED:
                raise VisualDesktopError("re_ground_failed", "Target could not be re-grounded")
            try:
                risk = self.validator.validate(current_grounding, fresh, approved=approved)
            except VisualValidationError as exc:
                raise VisualDesktopError(exc.code, str(exc)) from exc
            try:
                self._execute_gateway(current_grounding, fresh, risk, approved=approved)
            except VisualDesktopError as exc:
                if exc.code in {
                    "coordinate_stale",
                    "target_moved",
                    "window_changed",
                } and attempt < 2:
                    continue
                self._emit(
                    "visual_action_failed",
                    {"grounding_id": grounding_id, "code": exc.code, "attempts": attempt},
                )
                raise
            time.sleep(0.12)
            last_after = self.observe(
                scope=fresh.capture_scope,
                window_id=fresh.active_window.window_id if fresh.active_window else None,
            )
            after_image = self.captures.image(last_after.capture_id, require_latest=True)
            last_score = self.change_detector.compare(before_image, after_image)
            if last_score >= 0.003:
                result = VisualActionResult(
                    action_id=f"vact_{uuid.uuid4().hex[:18]}",
                    grounding_id=grounding_id,
                    status="verified",
                    attempts=attempt,
                    verification="Expected visual state changed after the governed action.",
                    before_observation_id=observation.observation_id,
                    after_observation_id=last_after.observation_id,
                    change_score=last_score,
                    used_accessibility=current_grounding.accessibility_match,
                )
                self._actions.append(result)
                self._emit(
                    "visual_action_verified",
                    {
                        "grounding_id": grounding_id,
                        "attempts": attempt,
                        "change_score": last_score,
                    },
                )
                return result.model_copy(deep=True)
            before_image = after_image
            current_observation = last_after
        result = VisualActionResult(
            action_id=f"vact_{uuid.uuid4().hex[:18]}",
            grounding_id=grounding_id,
            status="failed",
            attempts=2,
            verification="ACTION_VERIFICATION_FAILED",
            before_observation_id=current_observation.observation_id,
            after_observation_id=last_after.observation_id if last_after else None,
            change_score=last_score,
            used_accessibility=current_grounding.accessibility_match,
            error_code="ACTION_VERIFICATION_FAILED",
        )
        self._actions.append(result)
        self._emit(
            "visual_action_failed",
            {"grounding_id": grounding_id, "code": "ACTION_VERIFICATION_FAILED", "attempts": 2},
        )
        return result.model_copy(deep=True)

    def preview(self, observation_id: str) -> dict[str, Any]:
        observation = self._observation(observation_id)
        image = self.captures.image(observation.capture_id, require_latest=True)
        return {
            "capture_id": observation.capture_id,
            "image_base64": self.captures.preview_base64(observation.capture_id, image=image),
            "mime_type": "image/png",
            "expires_at": observation.capture_expires_at,
            "bounds": self.captures.metadata(observation.capture_id).bounds.model_dump(),
        }

    def stop(self) -> int:
        cleared = self.captures.clear()
        self.capabilities.settings.auto_refresh = False
        self._observations.clear()
        self._groundings.clear()
        return cleared

    def status(self) -> dict[str, Any]:
        recent_observations = list(self._observations.values())[-5:]
        recent_groundings = list(self._groundings.values())[-5:]
        return {
            "desktop_visual_layer": "VALIDATED",
            "vision_provider": self.capabilities.status(),
            "settings": self.capabilities.settings.model_dump(mode="json"),
            "active_captures": self.captures.active_count(),
            "recent_observations": [
                {
                    "observation_id": item.observation_id,
                    "timestamp": item.timestamp,
                    "capture_id": item.capture_id,
                    "capture_expires_at": item.capture_expires_at,
                    "vision_mode": item.vision_mode.value,
                    "elements": len(item.visual_elements),
                }
                for item in recent_observations
            ],
            "recent_groundings": [
                {
                    "grounding_id": item.grounding_id,
                    "target": item.target_description,
                    "status": item.status.value,
                    "confidence": item.confidence,
                }
                for item in recent_groundings
            ],
            "recent_actions": [item.model_dump(mode="json") for item in self._actions[-5:]],
        }

    def _execute_gateway(
        self,
        grounding: VisualGrounding,
        observation: DesktopObservation,
        risk,
        *,
        approved: bool,
    ) -> None:
        target = grounding.selected_element
        if target is None or observation.active_window is None:
            raise VisualDesktopError("target_missing", "Grounded target is unavailable")
        if grounding.accessibility_match and target.accessibility_element_id:
            step = ActionStep(
                step_id=f"visual-{uuid.uuid4().hex[:8]}",
                tool="windows_click_element",
                arguments={
                    "window_id": observation.active_window.window_id,
                    "element_id": target.accessibility_element_id,
                },
                rationale=f"Click grounded target: {(target.label or target.element_type)[:80]}",
                expected_state="Visual state changes and is re-observed",
                risk=risk,
            )
        else:
            # Coordinate fallback gets a gateway-owned full-screen freshness proof.
            frame = self.backend.capture_screen()
            current = self.backend.get_window_info(observation.active_window.window_id)
            bounds = grounding.selected_bounds
            if bounds is None:
                raise VisualDesktopError("target_missing", "Grounded bounds are unavailable")
            target_region_hash = self.backend.frame_region_hash(frame, bounds)
            step = ActionStep(
                step_id=f"visual-{uuid.uuid4().hex[:8]}",
                tool="windows_click_coordinate",
                arguments={
                    "window_id": current.window_id,
                    "accessibility_unavailable": True,
                    "window_hash": current.window_hash,
                    "screenshot_hash": frame.screenshot_hash,
                    "screen_bounds": frame.bounds.model_dump(),
                    "target_bounds": bounds.model_dump(),
                    "target_region_hash": target_region_hash,
                    "x": (bounds.left + bounds.right) // 2,
                    "y": (bounds.top + bounds.bottom) // 2,
                    "visual_grounding_id": grounding.grounding_id,
                },
                rationale=(
                    f"Click grounded visual target: {(target.label or target.element_type)[:80]}"
                ),
                expected_state="Visual state changes and is re-observed",
                risk=risk,
            )
        try:
            self.gateway.execute(step, task_id="visual-desktop", approved=approved)
        except ActionError as exc:
            raise VisualDesktopError(exc.code, str(exc)) from exc

    def _observation(self, observation_id: str) -> DesktopObservation:
        observation = self._observations.get(observation_id)
        if observation is None:
            raise VisualDesktopError("observation_not_found", "Desktop observation does not exist")
        return observation

    def _resolve_reference(self, target: str) -> str:
        normalized = "".join(target.strip().lower().split())
        references = {
            "it",
            "that",
            "thatbutton",
            "它",
            "那个",
            "那个按钮",
            "刚才那个",
            "刚才那个按钮",
        }
        if normalized not in references:
            return target
        for previous in reversed(self._groundings.values()):
            if previous.status is GroundingStatus.RESOLVED and previous.selected_element:
                return previous.selected_element.label or previous.target_description
        return target

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        session = self.sessions.current()
        task_id = session.session_id if session else "visual-desktop"
        self._events.emit(
            task_id=task_id,
            run_id=task_id,
            event_type=event_type,
            actor_type="system",
            actor_id="visual-desktop",
            summary=event_type.replace("_", " "),
            payload_safe=payload,
        )

    def _trim(self) -> None:
        while len(self._observations) > self.MAX_HISTORY:
            oldest = next(iter(self._observations))
            observation = self._observations.pop(oldest)
            self.captures.dispose(observation.capture_id)
        while len(self._groundings) > self.MAX_HISTORY:
            self._groundings.pop(next(iter(self._groundings)))
