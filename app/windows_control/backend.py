from __future__ import annotations

import base64
import ctypes
import hashlib
import io
import subprocess
import time
from typing import Any

from PIL import ImageGrab

from app.windows_control.models import AccessibilityElement, Bounds, ScreenFrame, WindowInfo
from app.windows_control.registry import RegisteredApplication


class AutomationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class WindowsAutomationBackend:
    """Real Windows backend. UI Automation is primary; raw coordinates are isolated fallback."""

    MAX_ELEMENTS = 300

    def __init__(self) -> None:
        self._element_cache: dict[str, tuple[str, dict[str, Any]]] = {}

    @staticmethod
    def _imports():
        try:
            import win32api  # type: ignore[import-untyped]
            import win32con  # type: ignore[import-untyped]
            import win32gui  # type: ignore[import-untyped]
            import win32process  # type: ignore[import-untyped]
            from pywinauto import Desktop, keyboard  # type: ignore[import-untyped]
        except ImportError as exc:  # pragma: no cover - guarded by Windows dependency marker
            raise AutomationError(
                "accessibility_unavailable", "Windows UI Automation unavailable"
            ) from exc
        return win32api, win32con, win32gui, win32process, Desktop, keyboard

    def is_locked(self) -> bool:
        user32 = ctypes.windll.user32
        handle = user32.OpenInputDesktop(0, False, 0x0100)
        if not handle:
            return True
        user32.CloseDesktop(handle)
        return False

    def has_elevation_prompt(self) -> bool:
        return any("user account control" in item.title.lower() for item in self.list_windows())

    def get_active_window(self) -> WindowInfo | None:
        _, _, win32gui, _, _, _ = self._imports()
        hwnd = int(win32gui.GetForegroundWindow())
        return self._window_from_handle(hwnd, active_handle=hwnd) if hwnd else None

    def list_windows(self) -> list[WindowInfo]:
        _, _, win32gui, _, _, _ = self._imports()
        active = int(win32gui.GetForegroundWindow())
        handles: list[int] = []

        def collect(hwnd, _extra):
            if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd).strip():
                handles.append(int(hwnd))

        win32gui.EnumWindows(collect, None)
        result = []
        for hwnd in handles[:100]:
            try:
                result.append(self._window_from_handle(hwnd, active_handle=active))
            except Exception:
                continue
        return result

    def get_window_info(self, window_id: str) -> WindowInfo:
        hwnd = self._parse_window_id(window_id)
        _, _, win32gui, _, _, _ = self._imports()
        if not win32gui.IsWindow(hwnd):
            raise AutomationError("window_changed", "Target window no longer exists")
        return self._window_from_handle(hwnd, active_handle=int(win32gui.GetForegroundWindow()))

    def capture_screen(self) -> ScreenFrame:
        image = ImageGrab.grab(all_screens=True)
        buf = io.BytesIO()
        image.save(buf, format="PNG", optimize=True)
        raw = buf.getvalue()
        user32 = ctypes.windll.user32
        left = int(user32.GetSystemMetrics(76))
        top = int(user32.GetSystemMetrics(77))
        width = int(user32.GetSystemMetrics(78)) or image.width
        height = int(user32.GetSystemMetrics(79)) or image.height
        return ScreenFrame(
            screenshot_hash=hashlib.sha256(raw).hexdigest(),
            bounds=Bounds(left=left, top=top, right=left + width, bottom=top + height),
            image_base64=base64.b64encode(raw).decode("ascii"),
        )

    def capture_window(self, window_id: str) -> ScreenFrame:
        info = self.get_window_info(window_id)
        box = (info.bounds.left, info.bounds.top, info.bounds.right, info.bounds.bottom)
        image = ImageGrab.grab(bbox=box)
        buf = io.BytesIO()
        image.save(buf, format="PNG", optimize=True)
        raw = buf.getvalue()
        return ScreenFrame(
            screenshot_hash=hashlib.sha256(raw).hexdigest(),
            bounds=info.bounds,
            image_base64=base64.b64encode(raw).decode("ascii"),
        )

    @staticmethod
    def frame_region_hash(frame: ScreenFrame, region: Bounds) -> str:
        """Hash a bounded physical-screen ROI without persisting or exposing its pixels."""
        if not (
            frame.bounds.left <= region.left < region.right <= frame.bounds.right
            and frame.bounds.top <= region.top < region.bottom <= frame.bounds.bottom
        ):
            raise AutomationError("coordinate_out_of_bounds", "Target region is outside the screen")
        from PIL import Image

        image = Image.open(io.BytesIO(base64.b64decode(frame.image_base64))).convert("RGB")
        crop = image.crop(
            (
                region.left - frame.bounds.left,
                region.top - frame.bounds.top,
                region.right - frame.bounds.left,
                region.bottom - frame.bounds.top,
            )
        )
        return hashlib.sha256(crop.tobytes()).hexdigest()

    def accessibility_tree(self, window_id: str) -> list[AccessibilityElement]:
        hwnd = self._parse_window_id(window_id)
        _, _, _, _, Desktop, _ = self._imports()
        try:
            root = Desktop(backend="uia").window(handle=hwnd).wrapper_object()
            wrappers = [root, *root.descendants()[: self.MAX_ELEMENTS - 1]]
        except Exception as exc:
            raise AutomationError(
                "accessibility_unavailable", "Accessibility tree unavailable"
            ) from exc
        elements: list[AccessibilityElement] = []
        for wrapper in wrappers:
            try:
                info = wrapper.element_info
                control_type = str(getattr(info, "control_type", "") or "")
                name = str(getattr(info, "name", "") or "")
                automation_id = str(getattr(info, "automation_id", "") or "")
                runtime_id = tuple(getattr(info, "runtime_id", ()) or ())
                password = bool(
                    getattr(getattr(info, "element", None), "CurrentIsPassword", False)
                ) or control_type.lower() in {
                    "password",
                    "credential",
                    "securetext",
                }
                rect = wrapper.rectangle()
                identity = {
                    "runtime_id": runtime_id,
                    "automation_id": automation_id,
                    "control_type": control_type,
                    "name": name,
                }
                token = hashlib.sha256(
                    f"{window_id}|{runtime_id}|{automation_id}|{control_type}|{name}".encode(
                        "utf-8"
                    )
                ).hexdigest()[:20]
                element_id = f"uia:{token}"
                self._element_cache[element_id] = (window_id, identity)
                elements.append(
                    AccessibilityElement(
                        element_id=element_id,
                        window_id=window_id,
                        name=name,
                        control_type=control_type,
                        automation_id=automation_id,
                        enabled=bool(wrapper.is_enabled()),
                        password=password,
                        bounds=Bounds(
                            left=int(rect.left),
                            top=int(rect.top),
                            right=int(rect.right),
                            bottom=int(rect.bottom),
                        ),
                    )
                )
            except Exception:
                continue
        return elements

    def launch(self, app: RegisteredApplication) -> WindowInfo:
        before = {item.window_id for item in self.list_windows()}
        process = subprocess.Popen(
            [str(app.executable), *app.arguments],
            shell=False,
            close_fds=True,
        )
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            windows = self.list_windows()
            process_window = next(
                (item for item in windows if item.process_id == process.pid), None
            )
            if process_window is not None and (
                not app.expected_title or app.expected_title.lower() in process_window.title.lower()
            ):
                return process_window
            new_windows = [item for item in windows if item.window_id not in before]
            for window in new_windows:
                if not app.expected_title or app.expected_title.lower() in window.title.lower():
                    return window
            # Single-instance applications such as Edge may reuse an existing
            # process/window and navigate it instead of creating a new HWND.
            # The executable and arguments are server-registered, so observing
            # the registered expected title after launch verifies that target.
            if app.expected_title and app.allow_existing_window:
                existing_match = next(
                    (
                        item
                        for item in windows
                        if app.expected_title.lower() in item.title.lower()
                    ),
                    None,
                )
                if existing_match is not None:
                    return existing_match
            time.sleep(0.25)
        raise AutomationError("action_timeout", f"Application window did not appear: {app.app_id}")

    def focus_window(self, window_id: str) -> WindowInfo:
        hwnd = self._parse_window_id(window_id)
        win32api, win32con, win32gui, _, Desktop, _ = self._imports()
        try:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            # Windows may reject a cross-process SetForegroundWindow unless the
            # current input queue recently handled user input. A bounded ALT pulse
            # is the standard non-elevated activation path; the target remains the
            # validated HWND and no model-supplied coordinate is involved.
            win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
            try:
                win32gui.BringWindowToTop(hwnd)
                win32gui.SetForegroundWindow(hwnd)
                Desktop(backend="uia").window(handle=hwnd).set_focus()
            finally:
                win32api.keybd_event(
                    win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0
                )
        except Exception as exc:
            raise AutomationError("window_not_active", "Unable to focus target window") from exc
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            current = self.get_active_window()
            if current is not None and current.window_id == window_id:
                return current
            time.sleep(0.05)
        raise AutomationError("window_not_active", "Target window did not become active")

    def find_element(
        self, window_id: str, *, control_types: tuple[str, ...], name: str = ""
    ) -> AccessibilityElement:
        normalized_types = {item.lower() for item in control_types}
        deadline = time.monotonic() + 1.5
        while True:
            candidates = self.accessibility_tree(window_id)
            for item in candidates:
                if item.control_type.lower() not in normalized_types:
                    continue
                if name and name.lower() not in item.name.lower():
                    continue
                if item.enabled:
                    return item
            if time.monotonic() >= deadline:
                break
            time.sleep(0.1)
        raise AutomationError("element_not_found", "Accessible target element not found")

    def click_element(self, window_id: str, element_id: str) -> AccessibilityElement:
        wrapper, element = self._resolve_element(window_id, element_id)
        if element.password:
            raise AutomationError("credential_field_forbidden", "Credential fields are forbidden")
        try:
            # Native Win32 list items can expose an Invoke wrapper even though the
            # underlying UIA Invoke pattern rejects the call. SelectionItem is the
            # semantic, coordinate-free action for these controls.
            if element.control_type.lower() == "listitem" and hasattr(wrapper, "select"):
                wrapper.select()
            elif hasattr(wrapper, "invoke"):
                wrapper.invoke()
            else:
                wrapper.click_input()
        except Exception as exc:
            raise AutomationError("action_timeout", "Accessible element invocation failed") from exc
        return element

    def select_item(self, window_id: str, element_id: str, value: str) -> AccessibilityElement:
        wrapper, element = self._resolve_element(window_id, element_id)
        if element.password:
            raise AutomationError("credential_field_forbidden", "Credential fields are forbidden")
        try:
            if hasattr(wrapper, "select"):
                wrapper.select(value)
            else:
                raise AttributeError("select is unavailable")
        except Exception as exc:
            raise AutomationError("action_timeout", "Accessible selection failed") from exc
        return element

    def set_text(self, window_id: str, element_id: str, text: str) -> str:
        if len(text) > 2000:
            raise AutomationError("input_too_long", "Text input exceeds 2000 characters")
        wrapper, element = self._resolve_element(window_id, element_id)
        if element.password:
            raise AutomationError("credential_field_forbidden", "Credential fields are forbidden")
        try:
            wrapper.set_focus()
            value = getattr(wrapper, "iface_value", None)
            if value is not None:
                value.SetValue(text)
            elif hasattr(wrapper, "set_edit_text"):
                wrapper.set_edit_text(text)
            else:
                self._send_unicode_text(text)
        except Exception:
            try:
                wrapper.set_focus()
                self._send_unicode_text(text)
            except Exception as exc:
                raise AutomationError("action_timeout", "Text input failed") from exc
        return self.read_element_text(window_id, element_id)

    def read_element_text(self, window_id: str, element_id: str) -> str:
        wrapper, element = self._resolve_element(window_id, element_id)
        if element.password:
            raise AutomationError("credential_field_forbidden", "Credential fields cannot be read")
        try:
            value = getattr(wrapper, "iface_value", None)
            if value is not None:
                return str(value.CurrentValue)
        except Exception:
            pass
        try:
            text_iface = getattr(wrapper, "iface_text", None)
            if text_iface is not None:
                return str(text_iface.DocumentRange.GetText(-1))
        except Exception:
            pass
        try:
            return "\n".join(str(item) for item in wrapper.texts())
        except Exception:
            return str(wrapper.window_text())

    def element_state(self, window_id: str, element_id: str) -> dict[str, Any]:
        wrapper, element = self._resolve_element(window_id, element_id)
        if element.password:
            return {"password": True, "value": None}
        state: dict[str, Any] = {"password": False}
        try:
            state["toggle_state"] = int(wrapper.get_toggle_state())
        except Exception:
            pass
        try:
            state["selected_text"] = str(wrapper.selected_text())
        except Exception:
            pass
        try:
            state["selected"] = bool(wrapper.is_selected())
        except Exception:
            pass
        try:
            state["text"] = self.read_element_text(window_id, element_id)
        except Exception:
            pass
        return state

    def press_key(self, window_id: str, key: str) -> None:
        allowed = {
            "TAB": "{TAB}",
            "ENTER": "{ENTER}",
            "ESC": "{ESC}",
            "SPACE": "{SPACE}",
            "UP": "{UP}",
            "DOWN": "{DOWN}",
            "LEFT": "{LEFT}",
            "RIGHT": "{RIGHT}",
            "HOME": "{HOME}",
            "END": "{END}",
        }
        normalized = key.upper()
        if normalized not in allowed:
            raise AutomationError("key_forbidden", "Key is outside the M5-A allowlist")
        self.focus_window(window_id)
        *_, keyboard = self._imports()
        keyboard.send_keys(allowed[normalized])

    def close_window(self, window_id: str) -> None:
        hwnd = self._parse_window_id(window_id)
        _, win32con, win32gui, _, _, _ = self._imports()
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)

    def click_coordinate(self, x: int, y: int) -> None:
        win32api, win32con, *_ = self._imports()
        win32api.SetCursorPos((x, y))
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, x, y, 0, 0)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, x, y, 0, 0)

    def _resolve_element(self, window_id: str, element_id: str):
        cached = self._element_cache.get(element_id)
        if cached is None or cached[0] != window_id:
            self.accessibility_tree(window_id)
            cached = self._element_cache.get(element_id)
        if cached is None or cached[0] != window_id:
            raise AutomationError("element_not_found", "Element ID is stale or unknown")
        identity = cached[1]
        _, _, _, _, Desktop, _ = self._imports()
        root = (
            Desktop(backend="uia").window(handle=self._parse_window_id(window_id)).wrapper_object()
        )
        wrappers = [root, *root.descendants()[: self.MAX_ELEMENTS - 1]]
        for wrapper in wrappers:
            info = wrapper.element_info
            candidate = {
                "runtime_id": tuple(getattr(info, "runtime_id", ()) or ()),
                "automation_id": str(getattr(info, "automation_id", "") or ""),
                "control_type": str(getattr(info, "control_type", "") or ""),
                "name": str(getattr(info, "name", "") or ""),
            }
            if candidate == identity:
                for element in self.accessibility_tree(window_id):
                    if element.element_id == element_id:
                        return wrapper, element
        raise AutomationError("element_not_found", "Element changed before action")

    def _window_from_handle(self, hwnd: int, *, active_handle: int) -> WindowInfo:
        _, _, win32gui, win32process, _, _ = self._imports()
        title = str(win32gui.GetWindowText(hwnd) or "")
        left, top, right, bottom = [int(v) for v in win32gui.GetWindowRect(hwnd)]
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        window_id = f"hwnd:{hwnd:x}"
        fingerprint = hashlib.sha256(
            f"{window_id}|{title}|{left},{top},{right},{bottom}".encode("utf-8")
        ).hexdigest()
        return WindowInfo(
            window_id=window_id,
            title=title,
            process_id=int(pid),
            app_name=title.split(" - ")[-1] if title else "",
            bounds=Bounds(left=left, top=top, right=right, bottom=bottom),
            is_active=hwnd == active_handle,
            window_hash=fingerprint,
        )

    @staticmethod
    def _parse_window_id(window_id: str) -> int:
        if not window_id.startswith("hwnd:"):
            raise AutomationError("window_changed", "Invalid window ID")
        try:
            return int(window_id[5:], 16)
        except ValueError as exc:
            raise AutomationError("window_changed", "Invalid window ID") from exc

    @staticmethod
    def _send_unicode_text(text: str) -> None:
        user32 = ctypes.windll.user32
        ulong_ptr = ctypes.POINTER(ctypes.c_ulong)

        class KeyInput(ctypes.Structure):
            _fields_ = [
                ("wVk", ctypes.c_ushort),
                ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", ulong_ptr),
            ]

        class InputUnion(ctypes.Union):
            _fields_ = [("ki", KeyInput)]

        class Input(ctypes.Structure):
            _fields_ = [("type", ctypes.c_ulong), ("union", InputUnion)]

        for char in text:
            code = ord(char)
            for flags in (0x0004, 0x0004 | 0x0002):
                item = Input(
                    type=1,
                    union=InputUnion(
                        ki=KeyInput(0, code, flags, 0, None),
                    ),
                )
                if user32.SendInput(1, ctypes.byref(item), ctypes.sizeof(item)) != 1:
                    raise AutomationError("action_timeout", "Unicode keyboard input failed")
