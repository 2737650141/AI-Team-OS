# M6-P Code Review

Date: 2026-08-12
Scope: M6-P diff only

## Summary

The change replaces the old task-scoped bypass boolean with one persistent, explicit-user setting
and one deterministic `ALLOW / ASK / BLOCK` decision path. The strongest aspects are live
re-evaluation for running tasks, hard-kernel precedence, separate Computer Control session
authority, recoverable workspace deletion, and visible automatic-action history.

## Finding resolved during review

1. **High — payments could have inherited generic external-effect auto-allow in Maximum.** Purchase,
   payment and order markers were moved into `SENSITIVE`; Maximum now requests one final confirmation.
2. **Medium — forbidden read-only tools could skip the permission policy.** ToolGateway now evaluates
   every registered tool before execution, not only write/dangerous tools.
3. **Medium — a legacy boolean bypass remained constructible.** `approval_bypass` was removed; tests
   now enter Maximum through the persistent PermissionStore.
4. **Low — task trace used an implicit alias.** `permission_mode_at_start` is now a first-class
   checkpoint and API field while the legacy field remains readable for checkpoint compatibility.

## Verification

- Complete backend regression, Ruff and mypy pass.
- Frontend typecheck, lint and component tests pass.
- GT-PERM01..20 plus the sensitive-payment regression pass.
- Browser ref-based acceptance covered default Standard, first Maximum confirmation, persistent
  change, status badge and switching back to Standard.
- Real Windows fixture acceptance passed 10/10, including password, UAC and STOP boundaries.

Final result: no open Blocker, High, Medium, or Low defect in the reviewed M6-P diff.
