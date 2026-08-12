# M6-P2 Independent Code Review

Reviewed 2026-08-12 after the final installed-app fixes.

## Verdict

`READY_FOR_CHIEF_REVIEW`, with one external release gate: clean-machine validation.

## Findings

- Blocking: 0 in the implementation. Clean-machine validation is an acceptance blocker, not an
  identified code defect.
- High: 0 open. The desktop session token originally appeared in child-process command arguments;
  it was moved to the child environment and is no longer visible in the command line.
- Medium: 0 open. Installed acceptance found and fixed private-network preflight, explicit Tauri
  window capability binding, and missing PyInstaller fixture data.
- Low: 1 known limitation. A deliberately underspecified “reply exactly OK” task completes the
  real planner call but fails the existing governed multi-agent execution acceptance after rework;
  this is workflow behavior, not a usage-accounting failure.

## Review focus

- Provider totals reconcile cache/reasoning subsets without double counting.
- Nullable fields preserve unavailable values instead of manufacturing zeros.
- Context compaction preserves deterministic critical fields.
- SQLite retention deletes telemetry only.
- Desktop API fails closed, binds loopback only, and authenticates each launch.
- Third-party types stay behind adapters and do not bypass gateway governance.

## Evidence

- Full Python regression passed.
- Frontend lint and production build passed.
- GT-TOK suite passed.
- The installed frozen sidecar completed a live DeepSeek request and the installed Usage page
  rendered provider-reported data.
