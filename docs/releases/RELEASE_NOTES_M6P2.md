# AI Team OS Developer Preview 0.1.0 — M6-P2

AI Team OS is a local-first Windows desktop preview of the governed JARVIS runtime. This build adds the installable Tauri desktop shell, persistent settings, complete tray lifecycle controls, real provider usage telemetry, context observability, and bounded sidecar recovery.

## Included

- Per-user NSIS installer with no Python, Node.js, Rust, or source checkout required at runtime.
- Dynamic loopback backend port with a fresh per-launch desktop session token.
- Single-instance behavior, close-to-tray, explicit quit, pause JARVIS, stop Computer Control, Voice on/off, and Settings tray actions.
- Provider-reported token usage where available, clearly labeled estimates otherwise, cost breakdowns, context-window status, and diagnostic-call separation.
- Persistent Permission Mode, provider configuration, memory, usage history, and task data across upgrade installs.

## Developer Preview limitations

- The installer is currently unsigned. Windows may show a reputation warning.
- Real model availability depends on the user's provider configuration, credentials, quota, network, and provider service status.
- Multimodal vision depends on separately configured compatible model capability; there is no silent fallback to an external provider.
- Wake-word support is experimental. Push-to-talk is the recommended voice input path.
- Chinese ASR quality depends on the locally selected or configured speech engine and microphone environment.
- Clean-machine Windows Sandbox or independent-VM validation is a release gate and must be recorded separately from same-host installation evidence.

## Data and privacy

Application state is stored under the current user's local application-data directory. The release bundle excludes credentials, databases, logs, screenshots, memory exports, task history, test artifacts, and environment files.
