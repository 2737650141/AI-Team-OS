from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


class RegistryError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RegisteredApplication:
    app_id: str
    executable: Path
    arguments: tuple[str, ...] = ()
    expected_title: str = ""
    allow_existing_window: bool = False


class ApplicationRegistry:
    """Server-owned allowlist. The model can request only app_id/path_id."""

    FORBIDDEN_APP_IDS = {"cmd", "powershell", "bash", "wsl", "terminal", "regedit"}

    def __init__(self, project_root: Path) -> None:
        win = Path(os.environ.get("SystemRoot", r"C:\Windows"))
        edge = self._first_existing(
            [
                Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
                / "Microsoft/Edge/Application/msedge.exe",
                Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
                / "Microsoft/Edge/Application/msedge.exe",
            ]
        )
        self._apps: dict[str, RegisteredApplication] = {
            "notepad": RegisteredApplication("notepad", win / "System32/notepad.exe"),
            "calculator": RegisteredApplication(
                "calculator", win / "System32/calc.exe", expected_title="Calculator"
            ),
            "file_explorer": RegisteredApplication(
                "file_explorer", win / "explorer.exe", expected_title="File Explorer"
            ),
        }
        if edge is not None:
            self._apps["browser"] = RegisteredApplication(
                "browser", edge, arguments=("--force-renderer-accessibility",)
            )
            self._apps["ai_team_os_browser"] = RegisteredApplication(
                "ai_team_os_browser",
                edge,
                arguments=("--force-renderer-accessibility", "http://127.0.0.1:5173"),
                expected_title="AI Team OS",
                allow_existing_window=True,
            )
        self._safe_paths = {"ai_team_os_project": project_root.resolve()}
        fixture = project_root / "fixtures/windows_uia/fixture.py"
        if fixture.is_file():
            self._apps["test_fixture"] = RegisteredApplication(
                "test_fixture",
                Path(sys.executable),
                arguments=(str(fixture),),
                expected_title="AI Team OS Windows UI Automation Test Fixture",
            )
        visual_fixture = project_root / "fixtures/visual_desktop/fixture.py"
        if visual_fixture.is_file():
            self._apps["visual_test_fixture"] = RegisteredApplication(
                "visual_test_fixture",
                Path(sys.executable),
                arguments=(str(visual_fixture),),
                expected_title="AI Team OS Visual Desktop Test App",
            )

    def get(self, app_id: str) -> RegisteredApplication:
        normalized = app_id.strip().lower()
        if normalized in self.FORBIDDEN_APP_IDS:
            raise RegistryError(
                "forbidden_application", "General shell and admin tools are unavailable"
            )
        if any(sep in normalized for sep in ("\\", "/", ":")):
            raise RegistryError("absolute_executable_rejected", "Executable paths are not accepted")
        app = self._apps.get(normalized)
        if app is None:
            raise RegistryError("unknown_application", f"Application is not registered: {app_id}")
        if not app.executable.is_file():
            raise RegistryError(
                "application_unavailable", f"Registered app is unavailable: {app_id}"
            )
        return app

    def safe_path(self, path_id: str) -> Path:
        if any(sep in path_id for sep in ("\\", "/", ":")):
            raise RegistryError("path_outside_allowlist", "Only registered path IDs are accepted")
        path = self._safe_paths.get(path_id)
        if path is None:
            raise RegistryError("path_outside_allowlist", "Path is outside the server allowlist")
        return path

    def catalog(self) -> dict[str, list[str]]:
        return {"applications": sorted(self._apps), "safe_paths": sorted(self._safe_paths)}

    @staticmethod
    def _first_existing(paths: list[Path]) -> Path | None:
        return next((path for path in paths if path.is_file()), None)
