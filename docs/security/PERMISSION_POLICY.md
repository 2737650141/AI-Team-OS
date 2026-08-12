# Permission Policy and Hard Safety Kernel

## Immutable boundary

All three modes block password-field access, browser/Windows credential export, API/private-key
extraction, UAC bypass or automated elevation consent, SecretStore bypass, safety-kernel mutation,
prompt/Agent mode escalation, malicious exfiltration, security-software disabling, and STOP bypass.

Maximum is an approval policy, not root access. Filesystem allowlists, command policy, tool role
allowlists, schemas, quotas, SecretStore, Windows session authority, UAC detection, password-field
detection and STOP all execute before or independently of user-mode convenience.

## Trust boundaries

- UI user gesture → settings API: the only permission-mode write path.
- Webpage/screen/model content → system: untrusted and read-only with respect to the setting.
- Risk labels → classifier: model hints cannot lower a hard-forbidden classification.
- Policy decision → gateway: every execution point enforces ALLOW/ASK/BLOCK.
- Automatic execution → audit: action, target, risk, mode, decision, reason, task and timestamp.

## Fail-safe behavior

- Missing or legacy configuration migrates to Standard.
- Unknown normal tools do not inherit Maximum implicitly; tool registration and role/schema checks
  remain mandatory.
- External/system effects outside the explicit goal ask even in Maximum.
- Sensitive final effects ask once instead of producing a chain of confirmations.
- STOP and UAC terminate/control independently of the policy decision.
