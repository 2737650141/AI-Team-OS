# M5-B Visual Desktop Intelligence evidence

Branch: `phase-5b/visual-desktop-intelligence`

The M5-A baseline was repaired for current Notepad/UIA behavior, passed GT-WIN01..10, committed as
`8900b72`, and fast-forwarded to local `main` before this branch was created. No remote, push, PR,
elevation, arbitrary shell capability, or frozen safety-boundary reduction was introduced.

## Deterministic and real acceptance

- GT-V01..12: 12/12 passed against the native visual fixture, including UIA/pixel fusion, a
  vision-only Canvas control, ambiguity, movement/staleness, DPI, prompt injection, password
  redaction, emergency cleanup, observe-only, icon grounding, and modal re-observation.
- REAL-V01..05: 5/5 passed on real Windows and the local AI Team OS page. The result correctly
  reports `LOCAL_FUSION`, Accessibility-first Settings action, observe-only pause grounding,
  Ground→Validate→Act→Verify refresh, and `VISION_MODEL=NOT_CONFIGURED`.
- Browser acceptance used a local-domain-only deterministic reference-click loop. It verified
  manual refresh, max-1-FPS auto refresh and pause, all overlay toggles, `OBSERVE · 0 ACTION`,
  target ambiguity preview, Chinese/English, and the external-vision consent warning/default-off
  state.

Machine-readable results are retained under ignored `artifacts/acceptance/m5b`:
`GT_VISION_RESULTS.json`, `REAL_VISION_RESULTS.json`, `BROWSER_ACCEPTANCE_RESULTS.json`, and the
M5-A regression result. Explicit screenshots are also ignored and excluded from packaging.

## Privacy evidence

The test suite asserts source roots contain no PNG/JPEG/WebP captures. Runtime persistence scans
found no raw screenshots. Stop leaves zero active captures. The source archive builder excludes
all screenshots and artifacts and performs the established secret scan before writing the zip.

## Reviews

The ordinary and security reviews are in `M5B_CODE_REVIEW.md` and `M5B_SECURITY_REVIEW.md`.
All blocker/high/medium findings were remediated and protected by tests before sign-off.

## Final regression

- Backend: 418 passed, 2 intentional skips.
- Ruff: passed for app, tests, and scripts.
- Mypy: passed for the full app source tree.
- Frontend: Vitest 9/9, TypeScript typecheck, ESLint, and production build passed.
- Dependency integrity: `pip check` passed; final `npm audit` reported zero vulnerabilities.
- M5-A real Windows regression: GT-WIN01..10 passed 10/10.
- M5-B visual fixture: GT-V01..12 passed 12/12 with zero screenshot persistence.
- Real Windows visual acceptance: REAL-V01..05 passed 5/5.
- Source package: `artifacts/review/m5b-source.zip`, 298 files; secret scan clean and image/artifact
  scan found zero prohibited entries.

## Status

```text
DESKTOP_VISUAL_LAYER = VALIDATED
MULTIMODAL_VISION_MODEL = NOT_CONFIGURED
```
