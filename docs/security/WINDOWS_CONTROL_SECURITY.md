# Windows control security and privacy (M5-A)

## Authority boundary

- Computer Control starts `OFF` and never auto-starts, including when memory requests it.
- Observe-only, low-risk control, and approval for every action are the only session capabilities.
- There is no unrestricted mode. “Expanded Task Capability” remains subject to security,
  forbidden-action, secret, approval, and OS policy.
- Paused, expired, stopped, locked, or missing sessions cannot invoke Windows tools.
- UAC detection terminates control with `ELEVATION_REQUIRED`; no elevation or administrator
  credential path exists.

## Approval and targets

- Medium/high actions require explicit approval in low-risk sessions; every write action requires
  approval in sessions configured to ask for every action.
- External-impact fixture clicks, text entry, coordinates, and window close use the approval path.
- A rejected approval is terminal for the task and the action is not invoked.
- Element IDs are re-resolved. Coordinates are accepted only as a stale-state-protected fallback.
- The registry accepts identifiers, never model-supplied executable or filesystem paths.

## Screen and accessibility privacy

- Screens exist as `ScreenFrame` values in process memory and are returned only to the active
  browser request. The service never writes them to SQLite, audit payloads, evidence, memory, task
  state, or Git.
- The UI requests an active-window capture when possible, reducing exposure compared with a full
  desktop capture. Refresh is manual and the frame is cleared when control stops.
- Acceptance PNGs under the ignored `artifacts/acceptance/m5a` directory were explicitly captured
  from Notepad, the isolated fixture, or the local control page. They are not part of the source
  package.
- Accessibility metadata can state that a password field exists but never returns its value.
  Password/credential/secure-text reads and writes are forbidden.
- Clipboard read and write are not implemented in M5-A.

## Local deployment boundary

The control API is an unauthenticated local single-user surface. The application entry point
refuses non-loopback binds and the standard launcher binds both API and UI to `127.0.0.1`. It must
not be exposed through a proxy, tunnel, port-forward, or public interface without a future
authentication and origin-protection design.

## Verified abuse cases

Automated and manual tests cover absolute executable rejection, unknown applications, forbidden
shells, paths outside the allowlist, password fields, UAC, stale coordinates, inactive/paused/
expired/stopped sessions, emergency-stop queue cancellation, screenshot ephemerality, and a hard
retry/replan bound.
