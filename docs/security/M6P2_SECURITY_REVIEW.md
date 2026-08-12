# M6-P2 Security Review

Reviewed 2026-08-12.

## Boundary assessment

- The packaged API binds only to an ephemeral `127.0.0.1` port.
- Every launch uses a fresh 48-character token generated from the operating-system RNG.
- The token is passed through the child environment, not command-line arguments or readiness files.
- Requests use constant-time token comparison; missing or invalid tokens return HTTP 401.
- CORS is restricted to Tauri origins and explicitly permits only the packaged private-network
  preflight. The frontend fails closed if the desktop backend does not become ready.
- The Content Security Policy permits connections only to Tauri IPC and loopback.
- Provider secrets remain DPAPI-encrypted in LocalAppData and are not written to usage telemetry.

## Telemetry privacy

The usage schema stores numeric counts, task/run/call identifiers, provider/model/role, timing,
source labels, and optional cost. It has no columns for prompts, assistant content, hidden
reasoning, raw memory, API keys, or other secrets.

## Findings

- Blocking: 0 open.
- High: 0 open. Command-line session-token exposure was fixed before the final build.
- Medium: 0 open. WebView2 PNA and capability binding were fixed and regression-tested.
- Low: 0 open.

The unsigned installer is a release/distribution limitation: Windows publisher trust warnings are
expected until a production code-signing certificate is configured. It does not change the local
runtime security boundary, but signing is required before a public production release.
