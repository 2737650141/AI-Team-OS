# M6-P Security Review

Date: 2026-08-12
Scope: global permission modes, approval policy, Windows actions, workspace writes, audit

## Trust boundaries

| Boundary | Control |
|---|---|
| User UI -> permission setting | `user_explicit_action` is mandatory; first Maximum enable also requires confirmation |
| Agent/web content -> permission setting | no task/model field exists; non-user sources are rejected |
| Action -> operating system/files | ToolGateway and WindowsActionGateway remain mandatory enforcement points |
| Maximum -> privileged OS boundary | password/secret extraction, UAC bypass, safety changes and STOP bypass remain blocked |
| Running task -> changed global mode | every governed action re-reads the persistent setting |

## Adversarial verification

- A model or webpage cannot submit a per-task permission override.
- `agent_change_permission_mode`, `prompt_change_permission_mode`, secret extraction and STOP bypass
  classify as `FORBIDDEN` and return `BLOCK` in every mode.
- A real password control rejects text access as `credential_field_forbidden`.
- UAC detection terminates Computer Control and returns `ELEVATION_REQUIRED`; no UAC click is made.
- Maximum cannot authorize unrequested external/system effects; `task_explicit=false` returns `ASK`.
- Payments, purchases, legal/financial submissions and private-data effects remain one final `ASK`
  even when explicitly requested in Maximum.
- Workspace validation, sensitive-path denial, registered application/path allowlists, budgets and
  STOP remain independent of permission mode.

## Review result

Critical 0 / High 0 / Medium 0 / Low 0 open findings.

The permission mode changes approval frequency; it does not grant new OS authority or broaden the
user's task goal.
