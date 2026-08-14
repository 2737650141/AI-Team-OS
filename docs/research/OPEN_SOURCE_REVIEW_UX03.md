# Open Source Review — UX-03 JARVIS Interaction Layer

Scope was intentionally limited to desktop notifications. Conversation, runtime events,
rollback, memory, voice, computer control, and usage all reused existing AI Team OS code.

## Candidate A — Tauri Notification Plugin

- Repository: `tauri-apps/plugins-workspace`, `plugins/notification`
- GitHub: https://github.com/tauri-apps/plugins-workspace/tree/v2/plugins/notification
- Purpose: native operating-system notifications and notification action callbacks.
- License: Apache-2.0 OR MIT.
- Activity: maintained in Tauri's official v2 plugins workspace; v2.3.3 is used by the
  official API example and supports Windows.
- Reviewed: repository README and plugin catalog, official JavaScript API and setup
  documentation, v2 releases/activity, Cargo/JS dependencies, capability permissions,
  example integration, action callback source/API, issue tracker, and security policy.
- Relevant components: `sendNotification`, permission request/status, `onAction`,
  `notification:default` capability.
- Reuse level: LEVEL 1 — Direct Dependency.
- Pros: official Tauri lifecycle, native installed-app behavior, typed JS API, Windows
  support, no custom toast process, click payload support.
- Cons: adds Rust/JS dependencies; Windows notifications require an installed app.
- Security: only `notification:default` is granted; notification payload contains a run id
  and human task title, never prompt content, secrets, evidence bodies, or model output.
- Decision: selected. Task completion/failure/approval notifications are preference-gated,
  deduplicated per run and event type, and action clicks return to the original JARVIS run.

## Candidate B — Web Notification API

- Repository: browser/WebView platform capability; no new repository dependency.
- Purpose: browser-origin notifications.
- License: platform API.
- Activity: maintained by browser vendors.
- Relevant components: `Notification.requestPermission`, `new Notification`.
- Reuse level: LEVEL 4 — Architecture Reference.
- Pros: no dependency.
- Cons: WebView/installed desktop behavior and notification click routing are less
  deterministic than Tauri's supported desktop plugin; does not integrate with Tauri
  capability governance.
- Security: browser permission prompt; origin-specific behavior.
- Decision: rejected for production Desktop notification delivery.

## Candidate C — Custom Windows Toast Bridge

- Repository: custom PowerShell/WinRT/Rust implementation.
- Purpose: invoke Windows toast APIs directly.
- License: custom implementation.
- Reuse level: LEVEL 5 — Custom Implementation (rejected).
- Pros: Windows-specific control.
- Cons: duplicate platform integration, packaging and identity edge cases, extra process or
  WinRT code, more tests and maintenance, no benefit over the official plugin.
- Security: would expand native command surface and require custom payload validation.
- Decision: rejected. `WHY_CUSTOM_IMPLEMENTATION` is not satisfied.

## Final decision

Use the official Tauri v2 notification plugin through a narrow UI adapter. It remains below
AI Team OS governance: notification eligibility comes from explicit Interaction Settings,
task data is read through authenticated local APIs, and the plugin cannot execute tasks,
change PermissionMode, approve actions, or bypass STOP.

Estimated avoided custom work: 2–4 engineering days plus ongoing Windows toast maintenance.
