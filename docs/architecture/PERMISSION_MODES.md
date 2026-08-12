# Permission Modes Architecture

M6-P replaces task-only approval switches with one persistent, explicit user setting.

```text
User UI action
→ PermissionStore (SQLite, default STANDARD)
→ PermissionRuntime (live read for every action)
→ RiskClassifier
→ PermissionPolicy: ALLOW / ASK / BLOCK
→ ToolGateway / WindowsActionGateway / Executor
→ audit + Recent Automatic Actions
```

## Modes

| Risk | Safe | Standard | Maximum |
|---|---|---|---|
| Read only / low | ALLOW | ALLOW | ALLOW |
| Normal write, patch, test, UI action | ASK | ALLOW | ALLOW |
| Destructive | ASK | ASK | ALLOW when task-related |
| External/system | ASK | ASK | ALLOW only when explicitly required by the user goal |
| Sensitive final effect | ASK | ASK | ASK once |
| Forbidden | BLOCK | BLOCK | BLOCK |

The task checkpoint stores `permission_mode` as the start-time trace snapshot. Enforcement does not
trust that snapshot: `PermissionRuntime` re-reads the current setting before every action. A change
from Maximum to Safe therefore immediately tightens a running task; a change in the other direction
applies only to subsequent actions.

Agents and task-create payloads cannot modify the setting. Only the dedicated Settings API accepts
`user_explicit_action=true`; Maximum requires a one-time persisted confirmation.

Computer Control remains independently OFF after restart and must have an active session before any
Windows action. Permission mode controls approval frequency, not session authority or task scope.
