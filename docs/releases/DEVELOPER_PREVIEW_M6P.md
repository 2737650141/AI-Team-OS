# Developer Preview — M6-P Permission Experience

- New installations and upgrades without an explicit setting use Standard mode.
- Safe, Standard and Maximum are persistent global settings, not per-task overrides.
- Standard automatically handles normal project writes, patches, tests, builds and UI input.
- Maximum removes ordinary approval interruptions for actions directly required by the user goal.
- Maximum has one first-use confirmation; the top-bar badge remains visible without repeated alerts.
- Password/secret extraction, UAC bypass, safety-kernel changes and STOP bypass remain blocked.
- Task details retain the start-mode snapshot while live enforcement follows a newer user change.
- Automatic action history records decision evidence without storing sensitive data.
# M6-P2 Desktop Release Completion and Usage Observatory

- Added Tauri 2 Windows shell, PyInstaller sidecar, current-user NSIS installer, single instance,
  tray lifecycle, ephemeral loopback port, and per-launch desktop authentication.
- Added provider-reported/estimated/unavailable token accounting, context window policy,
  structured compaction checkpoints, usage retention, breakdowns, timeline, and `/usage` UI.
- Verified live DeepSeek V4 Flash usage in the packaged application.
- Final installer: `artifacts/release/AI-Team-OS-x64-Setup.exe`.
- Clean-machine validation remains required before declaring M6-P complete.
