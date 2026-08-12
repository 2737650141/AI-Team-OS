# Open Source Review — M6-P Permission Modes

Date: 2026-08-12

## Capability

AI Team OS needs a local policy decision point for three user modes, eight deterministic risk
classes, an immutable hard-safety boundary, human-readable explanations, persistent user choice,
and enforcement inside Tool/Windows/Voice gateways. This is task-action governance, not user RBAC.

## Candidates

| Repository | License / activity | Relevant components | Windows / Python | Reuse level | Decision |
|---|---|---|---|---|---|
| [apache/casbin-pycasbin](https://github.com/apache/casbin-pycasbin) | Apache-2.0; active Apache project, production-ready label, async support and tests | PERM model, ACL/RBAC/ABAC, deny override, priority, adapters | Native Python, Windows-compatible | LEVEL 4 architecture reference | Strong general authorization library, but model/policy files and user/resource role machinery exceed a fixed 24-cell product matrix. |
| [open-policy-agent/opa](https://github.com/open-policy-agent/opa) | Apache-2.0; CNCF graduated, 200+ releases, external security audit | PDP/PEP split, Rego policy-as-code, explainable structured input, policy tests | Official Windows binary; integration adds a process/HTTP or Wasm runtime | LEVEL 4 architecture and testing reference | Excellent for organization-wide distributed policy; rejected as a runtime dependency because this is a single-user local desktop app and must have no policy service failure mode. |
| [cedar-policy/cedar](https://github.com/cedar-policy/cedar) | Apache-2.0; active, validator/analyzer and security guidance | explicit permit/forbid, schema validation, analyzable policies, bounded authorization | Rust-first; no first-party embedded Python package in the core repository | LEVEL 4 hard-forbid/schema reference | Useful deny-overrides and analyzability model; Rust/Wasm bridge is disproportionate for eight frozen risk classes. |
| [osohq/oso](https://github.com/osohq/oso) | Apache-2.0 library; Python package release cadence is old and current product focus has shifted | embedded Polar rules, application-object authorization | Python/Windows supported by legacy library | Rejected | Avoid a legacy embedded runtime and separate policy language for a tiny stable matrix. |

## Security and dependency review

- All primary candidates use permissive Apache-2.0 licensing.
- OPA introduces a downloaded executable/service and an additional local trust boundary.
- Cedar introduces a Rust/Wasm FFI supply-chain and packaging surface.
- Casbin/Oso allow runtime policy mutation APIs that would require another control preventing Agents
  from changing permission policy.
- No candidate can replace AI Team OS task-goal scope, SecretStore, STOP, UAC, workspace, approval,
  audit, or WindowsActionGateway controls.

## Decision

`LEVEL 5 — Custom governed gap implementation`, limited to the small deterministic matrix and a
SQLite settings/history store. `WHY_CUSTOM_IMPLEMENTATION`: the policy has exactly three frozen
modes and eight risk classes, must remain directly reviewable in Python, must work without network,
binary, subprocess, FFI or mutable policy files, and must not expose a policy-editing API to Agents.

The design reuses mature architecture rather than code:

```text
Action (untrusted description)
→ RiskClassifier (trusted normalization)
→ PermissionPolicy/PDP (ALLOW / ASK / BLOCK)
→ ToolGateway or WindowsActionGateway/PEP
→ Approval or execution
→ audit/history
```

No full fork and no third-party types cross the governance boundary.
