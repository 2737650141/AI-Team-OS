# Windows Action Layer (M5-A)

M5-A adds a local, Windows-only control plane that is off by default. A user must start a
`DeviceSession` before any observation or action tool is available. The supported lifecycle is
`active`, `paused`, `expired`, and `terminated`; stopping a session clears queued approvals,
invalidates Windows tools, clears the in-memory screen frame, and marks an in-flight task stopped.

The execution contract is:

```text
Observe -> Plan -> Validate -> Approve when required -> Act -> Observe again -> Verify -> Review
```

The real Supervisor and Planner classify a bounded intent and produce a user-visible plan. The
plan is accepted only when its tool sequence and arguments match the deterministic intent policy.
If bounded schema repair is exhausted, only a server-owned canonical plan for that already
validated intent may be used; the UI exposes this as `planner_recovered`. Every OS call then passes
through `WindowsActionGateway`; models never receive a backend, mouse, Windows API, executable
path, or general shell capability.

`ApplicationRegistry` owns executable paths and safe project paths. M5-A registers Notepad,
Calculator, File Explorer, Edge when available, the local AI Team OS console, and the isolated UIA
fixture. The model can request only an `app_id` or `path_id`. Shells, terminals, Registry Editor,
arbitrary executable paths, unknown applications, and paths outside the registry are rejected.

UI Automation is the primary interaction mechanism. Element actions are resolved again at action
time, credential fields are never read or written, ordinary text input is bounded to 2,000
characters, and keyboard actions use a small key allowlist. Raw coordinates are a high-risk
fallback and require an explicit prior accessibility failure, approval, matching active window,
window fingerprint, screen fingerprint, screen bounds, and in-bounds coordinates.

Each action is re-observed and verified. Transient failures receive at most two retries. After the
retry budget is exhausted, one bounded Supervisor replan may re-observe the same validated window
and discard only a stale accessibility token; it cannot substitute a different window, app, path,
coordinate, text, or tool. A subsequent failure ends the task.

The `/computer` page shows screen/control state, real Provider/model identity, current app, the
action plan, pending approvals, action history, verification results, and safety status in Chinese
and English. Screen refresh is manual; there is no background recording or continuous capture.

M5-A remains a local single-user preview. Sessions and tasks are process-memory state and do not
survive a backend restart. UI Automation coverage depends on the target application's Windows
accessibility support. Keyboard emergency stop is intentionally not claimed; the mandatory web
`STOP CONTROL` path is implemented and tested.
