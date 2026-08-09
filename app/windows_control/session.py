from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone

from app.windows_control.models import (
    DeviceSession,
    SessionCapability,
    SessionStatus,
    utc_now,
)


class SessionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class DeviceSessionManager:
    """In-memory, local-user session authority. Restart always returns control to OFF."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._session: DeviceSession | None = None

    def start(
        self,
        *,
        user_id: str,
        capability: SessionCapability,
        ttl_minutes: int = 15,
    ) -> DeviceSession:
        ttl_minutes = max(1, min(ttl_minutes, 60))
        now = datetime.now(timezone.utc)
        allowed = [
            "windows_get_active_window",
            "windows_list_windows",
            "windows_get_window_info",
            "windows_capture_screen",
            "windows_capture_window",
            "windows_get_accessibility_tree",
        ]
        if capability is not SessionCapability.OBSERVE_ONLY:
            allowed.extend(
                [
                    "windows_launch_app",
                    "windows_focus_window",
                    "windows_click_element",
                    "windows_set_text",
                    "windows_press_key",
                    "windows_close_window",
                    "windows_open_safe_path",
                    "windows_click_coordinate",
                ]
            )
        with self._lock:
            self._session = DeviceSession(
                session_id=uuid.uuid4().hex[:16],
                user_id=user_id,
                started_at=now.isoformat(timespec="seconds"),
                expires_at=(now + timedelta(minutes=ttl_minutes)).isoformat(timespec="seconds"),
                status=SessionStatus.ACTIVE,
                allowed_capabilities=allowed,
                capability=capability,
            )
            return self._session.model_copy(deep=True)

    def current(self) -> DeviceSession | None:
        with self._lock:
            self._expire_if_needed()
            return self._session.model_copy(deep=True) if self._session else None

    def require_active(self, tool: str | None = None) -> DeviceSession:
        with self._lock:
            self._expire_if_needed()
            if self._session is None or self._session.status is SessionStatus.INACTIVE:
                raise SessionError("inactive_session", "Computer Control session is not active")
            if self._session.status is SessionStatus.EXPIRED:
                raise SessionError("expired_session", "Computer Control session expired")
            if self._session.status is SessionStatus.TERMINATED:
                raise SessionError("action_after_stop", "Computer Control session was stopped")
            if self._session.status is SessionStatus.PAUSED:
                raise SessionError("paused_session", "Computer Control session is paused")
            if tool and tool not in self._session.allowed_capabilities:
                raise SessionError(
                    "permission_denied", f"Tool is disabled for this session: {tool}"
                )
            return self._session.model_copy(deep=True)

    def pause(self) -> DeviceSession:
        with self._lock:
            session = self.require_active()
            session.status = SessionStatus.PAUSED
            self._session = session
            return session.model_copy(deep=True)

    def resume(self) -> DeviceSession:
        with self._lock:
            self._expire_if_needed()
            if self._session is None:
                raise SessionError("inactive_session", "No Computer Control session")
            if self._session.status is SessionStatus.EXPIRED:
                raise SessionError("expired_session", "Computer Control session expired")
            if self._session.status is SessionStatus.TERMINATED:
                raise SessionError("action_after_stop", "Stopped sessions cannot resume")
            self._session.status = SessionStatus.ACTIVE
            return self._session.model_copy(deep=True)

    def terminate(self) -> DeviceSession | None:
        with self._lock:
            if self._session is None:
                return None
            self._session.status = SessionStatus.TERMINATED
            return self._session.model_copy(deep=True)

    def mark_action(self) -> None:
        with self._lock:
            if self._session is None:
                return
            self._session.action_count += 1
            self._session.last_action_at = utc_now()

    def set_active_window(self, window) -> None:
        with self._lock:
            if self._session is not None:
                self._session.active_window = window

    def force_expire_for_test(self) -> None:
        with self._lock:
            if self._session is not None:
                self._session.expires_at = (
                    datetime.now(timezone.utc) - timedelta(seconds=1)
                ).isoformat(timespec="seconds")
                self._expire_if_needed()

    def _expire_if_needed(self) -> None:
        if self._session is None or self._session.status in {
            SessionStatus.EXPIRED,
            SessionStatus.TERMINATED,
        }:
            return
        expires = datetime.fromisoformat(self._session.expires_at)
        if expires <= datetime.now(timezone.utc):
            self._session.status = SessionStatus.EXPIRED
