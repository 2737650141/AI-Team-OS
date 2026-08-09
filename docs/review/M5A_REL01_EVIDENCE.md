# REL-01 + M5-A evidence and independent review

Branch: `phase-5a/windows-action-layer`

Baseline: M4-B commit `e70d270` was fast-forwarded to local `main`; this branch was created from
that exact commit. The repository has no remote and this phase was not pushed or opened as a PR.

## REL-01

The previous real-model baseline passed 2 of 3 runs. The failed run was retained and traced to a
combination of role-capability mismatch, prompt-window evidence duplication, non-actionable
Reviewer rejection, implementation replay, and cached tool results being handled at the wrong
quota boundary. The fix preserved Reviewer correctness and finite rework: role contracts are
validated, verified evidence metadata is carried without demanding raw prompt duplication,
approved implementation replay is idempotent, and only scheduler-attested recovery/rework cache
replay avoids duplicate execution without weakening normal tool-loop quotas.

Five new `deepseek-v4-flash` runs passed 5/5 (100%). They made 44 real model calls with five
explicit approvals in total. Fake fallback, security violation, approval bypass, and infinite
rework were all zero. The failed first batch remains under
`artifacts/acceptance/rel01-history/failed-batch-1`; the final machine-readable result is
`artifacts/acceptance/rel01/REAL_RUNTIME_RELIABILITY.json`.

## M5-A real Windows acceptance

- Golden tasks GT-WIN01 through GT-WIN10: 10/10 passed through the real Windows backend.
- Fixture: native Win32 button, text box, password box, checkbox, combo box, list, dialog, and
  simulated UAC surface; click/text/check/select were performed through UI Automation.
- REAL-J01: real model launched Notepad, entered the exact Chinese acceptance text, re-observed it,
  passed Reviewer, and did not save.
- REAL-J02: observe-only window enumeration produced no write action and passed Reviewer. The
  retained first failure is explicitly marked as a PowerShell-to-Python encoding harness failure,
  not a product result.
- REAL-J03: real model launched only the registered local console URL
  `http://127.0.0.1:5173`, verified the page title, and passed Reviewer.
- REAL-J04: confirmed memory preference `控制电脑前先给我操作计划。`; the planned state was saved
  before action, then Notepad launch/text/verification passed.
- REAL-J05: stopped at explicit approval for the simulated external-impact click; rejection left
  fixture state unchanged and produced zero click action records.

Explicit, ignored acceptance evidence is under `artifacts/acceptance/m5a`. It contains only local
control-page, Notepad acceptance-text, and isolated fixture captures. A transient full-desktop
capture was not retained. Runtime persistence scans found no screen base64 or screenshot hash in
`data`; Git tracks no PNG/JPEG acceptance files, and the source package excludes `artifacts`.

## Browser acceptance

Codex used deterministic browser journeys (`open`, interactive snapshot, referenced click, fresh
snapshot) against `/computer`. It verified session inactive/active/paused, manual live-window
screen refresh, real Provider/model identity, action-plan-first behavior, pending approval,
rejection, completed task, Chinese/English copy, and top-level emergency stop. Emergency stop
terminated the session, disabled screen access, stopped the task, cleared pending/queued actions,
and produced no click record. Browser console errors: zero.

## Regression

- Backend: 395 collected; 393 passed and 2 intentional skips.
- Ruff: passed.
- Mypy: passed for 72 source files.
- Frontend Vitest: 9/9 passed.
- TypeScript typecheck: passed.
- ESLint: passed.
- Production build: passed (1,640 modules transformed).
- Windows manual integration: 10/10 passed and remains outside normal CI.

## Independent Reviewer

Review covered correctness, security, maintainability, performance, and tests. Two material issues
were found and fixed before closeout:

1. Edge single-instance window reuse had been generalized to every registered application, which
   could mistake an old fixture window for a new successful launch. Reuse is now an explicit
   registry capability enabled only for the local Edge console.
2. REL-01 cache replay initially made same-run repeated tool calls free, conflicting with the
   frozen loop/evidence quota. Normal duplicate calls now consume quota while only
   scheduler-attested checkpoint/rework replay may reuse a cached result without re-execution.

Open findings after fixes: Blocking 0, High 0, Medium 0. Two low limitations remain: process-memory
session/task state is lost on backend restart, and UI Automation coverage varies across third-party
applications. Both are documented scope limits rather than hidden fallbacks.
