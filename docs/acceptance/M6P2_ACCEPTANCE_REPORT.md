# M6-P2 Acceptance Report

Status is evidence-driven. Unit/golden, full regression, real-provider, packaged desktop, and
clean-machine results are recorded separately; an unexecuted environment check is never marked
as passed.

## Token observability

- Normalization: provider-specific adapters with no cache/reasoning double count.
- Persistence: local SQLite; restart and retention tests included.
- Privacy: schema test excludes prompt, response, secret, API key, and chain-of-thought fields.
- Real DeepSeek: bounded calls must return `usage_available=true` and `REPORTED` usage.

## Desktop release

- Shell: Tauri 2, single instance, tray, close-to-tray, graceful sidecar shutdown.
- Backend: PyInstaller windowed one-file, loopback-only dynamic port and per-launch auth token.
- Installer: NSIS current-user install. Artifact path and hash are recorded after a successful build.
- Clean Windows: installer launch, first-run, restart persistence, task run, Usage page, tray,
  single-instance, uninstall, and residue checks must be executed on the installed artifact.

## Measured acceptance (2026-08-12)

- Backend regression: full pytest suite passed with two pre-existing environment-gated skips.
- Frontend: ESLint and production Vite build passed.
- Golden observatory suite: 22 tests passed, covering GT-TOK01..20 plus desktop release guards.
- Packaged sidecar: real DeepSeek request returned HTTP 200 from the installed binary.
- Installed UI: dashboard and Usage page opened from the per-user NSIS installation; empty state
  displayed no invented zero values, and real provider data appeared after a live call.
- Latest installed live call: DeepSeek Official / `deepseek-v4-flash`, 659 input, 118 output,
  640 cached input (input subset), 777 total, reasoning unavailable, 1301 ms, $0.0001253,
  `usage_source=REPORTED`.
- Installed usage store: 3 live requests, 1,977 input, 346 output, 2,323 total tokens.
- Desktop boundary: random loopback port observed; unauthenticated request returned HTTP 401;
  second launch kept one main instance; closing the main window kept the tray process alive.
- Upgrade install preserved LocalAppData provider configuration, DPAPI secret, permission setting,
  and usage history.

## Defects found and fixed during installed acceptance

1. WebView2 private-network preflight lacked `Access-Control-Allow-Private-Network`.
2. The Tauri capability was not explicitly attached to the `main` window.
3. PyInstaller omitted `app/tools/fixtures`, causing installed task creation to return HTTP 500.

All three have regression guards and were rebuilt into the final installer.

## Remaining release gate

Windows Sandbox is not installed on this host, and no clean Windows VM was available. Therefore
`CLEAN_INSTALL` remains **NOT VALIDATED** even though per-user install, launch, upgrade, live model
usage, and persistence were validated on the current Windows machine. The phase may be reviewed,
but M6-P must not be declared complete until the final installer is exercised on a clean Windows
environment with no Python, Node, or source tree.
