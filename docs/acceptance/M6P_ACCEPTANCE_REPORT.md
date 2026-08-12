# M6-P Permission Experience Acceptance Report

```text
PHASE: M6-P / 018-A
STATUS: READY_FOR_CHIEF_REVIEW
BRANCH: phase-6p/permission-experience

PERMISSION_MODES:
- Safe: read-only/low-risk auto; writes, tests, normal UI input and state changes ask
- Standard: normal project writes, patches, tests and ordinary Windows actions auto
- Maximum: task-required normal, destructive, allowed system and external effects auto
- Default: STANDARD
- Persistent: SQLite PermissionModeSetting outside Memory and task state
- Restart persistence: PASS
- Running task update: live re-read plus permission_mode_changed trace event

APPROVAL:
- Safe normal task: paused at patch confirmation
- Standard normal task: completed with 0 ordinary approvals
- Maximum normal task: completed with 0 ordinary approvals
- Sensitive action: one final ASK
- Hard forbidden: BLOCK

SECURITY_KERNEL:
- Secret: BLOCK
- Credential fields: BLOCK in real Windows fixture
- UAC: ELEVATION_REQUIRED; session terminated
- Prompt injection: cannot change mode
- Agent escalation: cannot change mode
- STOP: always works and remains above permission mode

REAL_ACCEPTANCE:
- Safe approvals: 1 expected patch confirmation
- Standard approvals: 0 for complete sandbox code-fix/test/review flow
- Maximum approvals: 0 for the same complete flow
- Maximum full autonomous task: completed, tests passed, Reviewer history present
- File deletion: Standard preserved disposable file and asked; Maximum moved it to recoverable trash
- Windows: 10/10 baseline checks plus exact Safe/Standard/Maximum matrix passed on real UI Automation
- Browser: default/Maximum-confirm/persistence/Standard-switch passed

GOLDEN:
- GT-PERM01..20: PASS
- Sensitive payment regression: PASS

TESTS:
- Backend: 474 passed, 2 conditional skips (476 collected)
- Ruff: PASS
- mypy: PASS (99 source files)
- Frontend: typecheck PASS; lint PASS; 10 Vitest PASS

CODEX:
- Permission tests: PASS
- Blocking: 0
- High: 0
- Medium: 0
- Low: 0

OPEN_SOURCE_REUSE:
- Projects researched: PyCasbin, Open Policy Agent, Cedar, Oso
- Direct dependencies: none
- Adapter integrations: none in this bounded phase
- Components reused: existing SQLite, gateways, approval, audit, workspace and Windows adapters
- Architecture references: centralized policy decision point and deny-overrides concepts
- Rejected projects: all four as runtime dependencies for this fixed eight-risk/three-mode matrix
- License review: all reviewed candidates Apache-2.0; no copied third-party code
- Custom code still required: small deterministic local matrix and persistent explicit-user setting
- Estimated avoided custom work: no speculative general policy language or service lifecycle added

PROOF:
User selects a mode once -> setting survives restart/new task -> every later action reads that mode
until the user explicitly changes it.
```
