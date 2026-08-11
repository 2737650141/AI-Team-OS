from __future__ import annotations

import base64
import ctypes
import hashlib
import io
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# MSS documents that DPI-aware packages imported before MSS can distort monitor coordinates.
# Keep this import first and isolate all MSS types inside this adapter.
import mss
from PIL import Image, ImageGrab

from app.desktop_vision.models import CaptureMetadata, CaptureScope, MonitorInfo
from app.windows_control.backend import WindowsAutomationBackend
from app.windows_control.models import Bounds


class CaptureError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class _StoredCapture:
    metadata: CaptureMetadata
    image: Image.Image


class ScreenCaptureService:
    """In-memory Windows capture adapter with a strict session and TTL lifecycle."""

    MAX_TTL_SECONDS = 60
    MAX_DIMENSION = 16_384

    def __init__(
        self,
        backend: WindowsAutomationBackend,
        *,
        ttl_seconds: int = 45,
    ) -> None:
        if not 1 <= ttl_seconds <= self.MAX_TTL_SECONDS:
            raise ValueError("capture TTL must be between 1 and 60 seconds")
        self.backend = backend
        self.ttl_seconds = ttl_seconds
        self._captures: dict[str, _StoredCapture] = {}
        self._latest_capture_id: str | None = None
        self._lock = threading.RLock()

    @property
    def latest_capture_id(self) -> str | None:
        with self._lock:
            self.cleanup_expired()
            return self._latest_capture_id

    def monitor_layout(self) -> list[MonitorInfo]:
        scale = self._system_scale_factor()
        with mss.MSS() as client:
            monitors = list(client.monitors[1:])
        return [
            MonitorInfo(
                monitor_id=str(index),
                bounds=Bounds(
                    left=int(item["left"]),
                    top=int(item["top"]),
                    right=int(item["left"] + item["width"]),
                    bottom=int(item["top"] + item["height"]),
                ),
                primary=index == 1,
                scale_factor=scale,
            )
            for index, item in enumerate(monitors, start=1)
        ]

    def capture_full_screen(self, *, session_id: str) -> CaptureMetadata:
        with mss.MSS() as client:
            monitor = dict(client.monitors[0])
            image = self._mss_image(client.grab(monitor))
        bounds = Bounds(
            left=int(monitor["left"]),
            top=int(monitor["top"]),
            right=int(monitor["left"] + monitor["width"]),
            bottom=int(monitor["top"] + monitor["height"]),
        )
        return self._store(
            image,
            scope=CaptureScope.FULL_SCREEN,
            bounds=bounds,
            session_id=session_id,
        )

    def capture_monitor(self, monitor_id: str, *, session_id: str) -> CaptureMetadata:
        try:
            index = int(monitor_id)
        except ValueError as exc:
            raise CaptureError("monitor_not_found", "Monitor identifier is invalid") from exc
        with mss.MSS() as client:
            if index < 1 or index >= len(client.monitors):
                raise CaptureError("monitor_not_found", "Monitor does not exist")
            monitor = dict(client.monitors[index])
            image = self._mss_image(client.grab(monitor))
        bounds = Bounds(
            left=int(monitor["left"]),
            top=int(monitor["top"]),
            right=int(monitor["left"] + monitor["width"]),
            bottom=int(monitor["top"] + monitor["height"]),
        )
        return self._store(
            image,
            scope=CaptureScope.MONITOR,
            bounds=bounds,
            session_id=session_id,
            monitor_id=str(index),
        )

    def capture_active_window(self, *, session_id: str) -> CaptureMetadata:
        window = self.backend.get_active_window()
        if window is None:
            raise CaptureError("window_not_active", "No active window is available")
        return self.capture_window(window.window_id, session_id=session_id, active=True)

    def capture_window(
        self, window_id: str, *, session_id: str, active: bool = False
    ) -> CaptureMetadata:
        window = self.backend.get_window_info(window_id)
        bounds = window.bounds
        self._validate_bounds(bounds)
        hwnd = int(window_id.split(":", 1)[1], 16)
        foreground = self.backend.get_active_window()
        is_active = foreground is not None and foreground.window_id == window_id
        if active and not is_active:
            raise CaptureError("window_not_active", "Active window changed before capture")
        if is_active:
            # The on-screen pixels are authoritative for a focused visual action and include
            # custom canvas surfaces that may not implement WM_PRINTCLIENT. MSS consumes the
            # same physical coordinate system as Win32/UIA, including negative origins and DPI.
            with mss.MSS() as client:
                image = self._mss_image(
                    client.grab(
                        {
                            "left": bounds.left,
                            "top": bounds.top,
                            "width": bounds.width,
                            "height": bounds.height,
                        }
                    )
                )
        else:
            # Pillow's HWND capture uses the native window path and remains valid when
            # another window overlaps conventional targets. Custom surfaces may return
            # accessibility-only observations until the user focuses them again.
            try:
                image = ImageGrab.grab(window=hwnd).convert("RGB")
            except (OSError, TypeError):
                image = ImageGrab.grab(
                    bbox=(bounds.left, bounds.top, bounds.right, bounds.bottom), all_screens=True
                ).convert("RGB")
        return self._store(
            image,
            scope=CaptureScope.ACTIVE_WINDOW if is_active else CaptureScope.WINDOW,
            bounds=bounds,
            session_id=session_id,
            window_id=window.window_id,
            window_hash=window.window_hash,
            scale_factor=self._window_scale_factor(window.window_id),
        )

    def capture_region(
        self,
        bounds: Bounds,
        *,
        session_id: str,
        window_id: str | None = None,
    ) -> CaptureMetadata:
        self._validate_bounds(bounds)
        window_hash = None
        if window_id:
            window = self.backend.get_window_info(window_id)
            if not self._contains(window.bounds, bounds):
                raise CaptureError("region_out_of_bounds", "Region is outside the target window")
            window_hash = window.window_hash
        with mss.MSS() as client:
            shot = client.grab(
                {
                    "left": bounds.left,
                    "top": bounds.top,
                    "width": bounds.width,
                    "height": bounds.height,
                }
            )
            image = self._mss_image(shot)
        return self._store(
            image,
            scope=CaptureScope.REGION,
            bounds=bounds,
            session_id=session_id,
            window_id=window_id,
            window_hash=window_hash,
            scale_factor=self._window_scale_factor(window_id) if window_id else None,
        )

    def metadata(self, capture_id: str, *, require_latest: bool = False) -> CaptureMetadata:
        with self._lock:
            self.cleanup_expired()
            record = self._captures.get(capture_id)
            if record is None:
                raise CaptureError("capture_expired", "Capture is missing or expired")
            if require_latest and capture_id != self._latest_capture_id:
                raise CaptureError("stale_capture", "A newer capture invalidated this grounding")
            return record.metadata.model_copy(deep=True)

    def image(self, capture_id: str, *, require_latest: bool = False) -> Image.Image:
        with self._lock:
            metadata = self.metadata(capture_id, require_latest=require_latest)
            return self._captures[metadata.capture_id].image.copy()

    def preview_base64(
        self,
        capture_id: str,
        *,
        image: Image.Image | None = None,
        max_dimension: int = 1600,
    ) -> str:
        if not 256 <= max_dimension <= 4096:
            raise CaptureError("invalid_image_size", "Preview dimension is outside policy")
        selected = image.copy() if image is not None else self.image(capture_id)
        selected.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        selected.save(buffer, format="PNG", optimize=True)
        return base64.b64encode(buffer.getvalue()).decode("ascii")

    def dispose(self, capture_id: str) -> None:
        with self._lock:
            record = self._captures.pop(capture_id, None)
            if record is not None:
                record.image.close()
            if self._latest_capture_id == capture_id:
                self._latest_capture_id = None

    def cleanup_expired(self) -> int:
        with self._lock:
            now = datetime.now(timezone.utc)
            expired = [
                capture_id
                for capture_id, record in self._captures.items()
                if datetime.fromisoformat(record.metadata.expires_at) <= now
            ]
            for capture_id in expired:
                self.dispose(capture_id)
            return len(expired)

    def clear(self) -> int:
        with self._lock:
            count = len(self._captures)
            for record in self._captures.values():
                record.image.close()
            self._captures.clear()
            self._latest_capture_id = None
            return count

    def active_count(self) -> int:
        with self._lock:
            self.cleanup_expired()
            return len(self._captures)

    def current_scale_factor(self, window_id: str | None = None) -> float:
        return self._window_scale_factor(window_id)

    @staticmethod
    def transform_point(
        x: float, y: float, *, origin: tuple[int, int], scale_factor: float
    ) -> tuple[int, int]:
        if scale_factor <= 0:
            raise ValueError("scale factor must be positive")
        return (
            int(round(origin[0] + x * scale_factor)),
            int(round(origin[1] + y * scale_factor)),
        )

    def _store(
        self,
        image: Image.Image,
        *,
        scope: CaptureScope,
        bounds: Bounds,
        session_id: str,
        monitor_id: str | None = None,
        window_id: str | None = None,
        window_hash: str | None = None,
        scale_factor: float | None = None,
    ) -> CaptureMetadata:
        self._validate_bounds(bounds)
        image = image.convert("RGB")
        capture_id = f"cap_{uuid.uuid4().hex[:20]}"
        now = datetime.now(timezone.utc)
        content_hash = hashlib.sha256(image.tobytes()).hexdigest()
        metadata = CaptureMetadata(
            capture_id=capture_id,
            timestamp=now.isoformat(timespec="milliseconds"),
            expires_at=(now + timedelta(seconds=self.ttl_seconds)).isoformat(
                timespec="milliseconds"
            ),
            scope=scope,
            monitor_id=monitor_id,
            window_id=window_id,
            width=image.width,
            height=image.height,
            scale_factor=scale_factor or self._system_scale_factor(),
            bounds=bounds,
            image_ref_ephemeral=f"memory://desktop-capture/{capture_id}",
            content_hash=content_hash,
            session_id=session_id,
            window_hash=window_hash,
        )
        with self._lock:
            self.cleanup_expired()
            self._captures[capture_id] = _StoredCapture(metadata=metadata, image=image)
            self._latest_capture_id = capture_id
        return metadata.model_copy(deep=True)

    @staticmethod
    def _mss_image(shot) -> Image.Image:
        return Image.frombytes("RGB", shot.size, shot.rgb)

    @classmethod
    def _validate_bounds(cls, bounds: Bounds) -> None:
        if bounds.width <= 0 or bounds.height <= 0:
            raise CaptureError("invalid_region", "Capture region must have positive dimensions")
        if bounds.width > cls.MAX_DIMENSION or bounds.height > cls.MAX_DIMENSION:
            raise CaptureError("capture_too_large", "Capture dimensions exceed local policy")

    @staticmethod
    def _contains(outer: Bounds, inner: Bounds) -> bool:
        return (
            outer.left <= inner.left
            and outer.top <= inner.top
            and outer.right >= inner.right
            and outer.bottom >= inner.bottom
        )

    @staticmethod
    def _system_scale_factor() -> float:
        try:
            dpi = int(ctypes.windll.user32.GetDpiForSystem())
            return round(max(dpi, 96) / 96.0, 3)
        except Exception:
            return 1.0

    @staticmethod
    def _window_scale_factor(window_id: str | None) -> float:
        if not window_id:
            return ScreenCaptureService._system_scale_factor()
        try:
            hwnd = int(window_id.split(":", 1)[1], 16)
            dpi = int(ctypes.windll.user32.GetDpiForWindow(hwnd))
            return round(max(dpi, 96) / 96.0, 3)
        except Exception:
            return ScreenCaptureService._system_scale_factor()
