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
4. PyInstaller's two-process one-file bootstrap could leave the worker behind if the desktop shell
   was terminated; the sidecar now watches the shell PID and exits with it.

All four have regression guards and were rebuilt into the final installer.

## Final release closure (2026-08-14)

- Final source gates: 596 backend tests passed, 2 environment-gated tests skipped; Ruff, mypy,
  `pip check`, TypeScript, ESLint, 13 frontend tests, production Vite build, Rust release build,
  PyInstaller, NSIS, and npm high-severity audit all passed. The npm audit reported 0
  vulnerabilities.
- Release output contains only `AI-Team-OS-x64-Setup.exe`, `SHA256SUMS.txt`, and
  `RELEASE_NOTES.md`. Installer size is 100,361,882 bytes; SHA-256 is
  `85BC1093803E5A39703E5957E6E6DA86C5B58B865D46BB27527E6303814D0065`.
- Upgrade installation exited 0. The existing audit and checkpoint database files retained their
  exact pre-upgrade sizes and SHA-256 hashes.
- Installed startup was measured at 1.15 seconds. A second launch retained one desktop instance;
  the one-file sidecar had one bootstrap root and one worker, both belonging to that desktop
  session.
- Terminating the desktop parent left 0 sidecar processes. Closing the main window hid the window
  while retaining one desktop session, confirming close-to-tray behavior.
- The installed backend listened only on dynamic `127.0.0.1:50425`; an unauthenticated health
  request returned HTTP 401.
- Installed UI showed system online, zero pending approvals, persisted Maximum permission mode,
  Developer Preview 0.1.0, and the Usage page's Reported/Estimated/Unavailable labels. The
  installed store displayed 9 requests and 8,806 tokens, including a separate Diagnostic scope.
- The six tray commands are release-compiled and covered by the desktop contract test. Windows 11
  did not expose the hidden notification icon to UI Automation on this host, so per-menu installed
  clicking is not claimed as passed; close-to-tray itself was exercised successfully.
- The installer is unsigned, as stated in the release notes.

## Remaining release gate

Windows Sandbox, Hyper-V cmdlets, VirtualBox, and VMware were not available on this host, and the
Windows optional-feature query required elevation. No UAC bypass or automatic elevation was
attempted. Therefore
`CLEAN_INSTALL` remains **NOT VALIDATED** even though per-user install, launch, upgrade, live model
usage, and persistence were validated on the current Windows machine. The phase may be reviewed,
but M6-P must not be declared complete until the final installer is exercised on a clean Windows
environment with no Python, Node, or source tree.
