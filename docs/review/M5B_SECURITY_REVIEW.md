# M5-B independent security review

## Threat model

Primary attackers are malicious screen content, a compromised or malformed future vision
provider, stale desktop state, crafted local API requests, and accidental screenshot leakage. The
highest-impact assets are Windows input authority, credentials visible on screen, local project
data, provider secrets, and user privacy.

## Abuse cases verified

- Visual prompt injection cannot become authority or a tool request.
- Password regions are redacted before any possible provider boundary and cannot be targeted.
- External processing is default-deny and requires verified capability, adapter, and consent.
- Provider output cannot forge UIA identity or escape the screenshot rectangle.
- Stale capture, target movement, window/focus change, resolution change, DPI change, stop,
  session expiry, lock, and UAC fail closed.
- Coordinate actions remain inside a fresh target ROI and the active window.
- Screens do not appear in persisted runtime stores or the source package.

## Supply-chain review

The phase directly reuses Pillow, MSS, OpenCV headless, and the existing pywinauto adapter under
permissive licenses documented in `docs/research/OPEN_SOURCE_REVIEW_M5B.md`. `pip check` reports a
consistent Python environment. The frontend audit initially found vulnerable legacy Vite/Vitest
and React Router versions, including a Windows development-server path issue. Vite, Vitest,
React Router, and the React Vite plugin were upgraded to current compatible releases; tests,
typecheck, lint, production build, and `npm audit` then passed with zero reported vulnerabilities.

## Residual risk

Password redaction depends on UIA metadata/terms and cannot guarantee detection of secrets painted
inside an inaccessible canvas. For that reason external vision remains off by default and the UI
warns users not to enable it on sensitive screens. Visual verification detects visible change; it
does not prove semantic business success on every third-party application.

## Result

Open findings: Critical/Blocking 0, High 0, Medium 0, Low 0. The two residual limitations above are
documented product constraints rather than bypasses.
