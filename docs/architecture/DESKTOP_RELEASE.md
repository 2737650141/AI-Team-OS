# Windows Desktop Release

AI Team OS uses Tauri 2 as a thin desktop shell and a PyInstaller one-file Python sidecar.
Tauri owns single-instance activation, the tray, close-to-tray behavior, graceful quit, and the
current-user NSIS installer. The Python process runs without a console window.

At every launch the sidecar binds an ephemeral `127.0.0.1` port. It writes readiness to the
per-user application-data directory; the webview waits for readiness and then sends a random
48-character session token on every request, including the authenticated event stream. The API
rejects requests without this per-process token. Neither port nor token is fixed or persisted.

App data, provider configuration, usage history, and permissions live under Tauri's per-user
LocalAppData directory. Closing the window hides it; Quit stops the child backend. A second launch
focuses the existing window.

Build with `scripts/build_desktop_release.ps1`. The expected artifact is
`artifacts/release/AI-Team-OS-x64-Setup.exe` with a SHA-256 printed by the build.
