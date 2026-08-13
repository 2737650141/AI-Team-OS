from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_desktop_tray_exposes_required_product_actions() -> None:
    rust = (ROOT / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
    bridge = (ROOT / "web" / "src" / "components" / "DesktopTrayBridge.tsx").read_text(
        encoding="utf-8"
    )

    for action in (
        "show",
        "pause_jarvis",
        "stop_computer",
        "toggle_voice",
        "settings",
        "quit",
    ):
        assert f'"{action}"' in rust
    assert 'app.emit("desktop-tray-action"' in rust
    assert 'listen<string>("desktop-tray-action"' in bridge
    assert "api.pauseVoice()" in bridge
    assert "api.pauseComputer()" in bridge
    assert "api.stopComputer()" in bridge
    assert "api.startVoice()" in bridge
    assert 'navigate("/settings")' in bridge


def test_release_builder_emits_required_release_files() -> None:
    script = (ROOT / "scripts" / "build_desktop_release.ps1").read_text(encoding="utf-8")

    assert '"AI-Team-OS-x64-Setup.exe"' in script
    assert '"SHA256SUMS.txt"' in script
    assert '"RELEASE_NOTES.md"' in script
    assert "Get-FileHash" in script
    assert (ROOT / "docs" / "releases" / "RELEASE_NOTES_M6P2.md").is_file()


def test_settings_identifies_the_build_as_developer_preview() -> None:
    settings = (ROOT / "web" / "src" / "pages" / "Settings.tsx").read_text(
        encoding="utf-8"
    )

    assert "Developer Preview" in settings
    assert "开发者预览版" in settings
    assert "Version 0.1.0" in settings
