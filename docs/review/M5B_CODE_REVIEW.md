# M5-B independent code review

## Scope

Reviewed the desktop-vision package, M5-A gateway integration, FastAPI contracts, React UI,
fixture, deterministic/real acceptance harnesses, dependency changes, and tests for correctness,
maintainability, performance, and regression risk.

## Findings fixed before sign-off

1. **Blocker — non-active capture scope race.** `capture_window` reused a variable for both the
   caller's active-window requirement and the current foreground window. A different foreground
   window could make a normal HWND capture appear to be `ACTIVE_WINDOW`. The variables are now
   separate and an active-window focus race fails closed. Two regression tests cover both paths.
2. **High — coordinate point/target binding.** The gateway verified screen and target-region
   freshness but did not independently require the requested point to be inside the proven target
   rectangle. It now requires a target proof on every coordinate action, bounds the rectangle to
   the active window, and bounds the click to the rectangle.
3. **High — external route bypass.** A direct API request could set the external-processing flag
   with consent while no verified adapter was registered. Server-side policy now requires verified
   image capability plus an installed adapter before the gate can turn on.
4. **Medium — provider identity trust.** External elements could retain a provider-supplied
   Accessibility ID or out-of-capture bounds. Provider output is now bounded, normalized as
   untrusted external pixels, stripped of Accessibility identity and arbitrary attributes, and
   filtered to the capture region.
5. **Medium — deprecated capture constructor.** The MSS adapter used the deprecated convenience
   constructor. It now uses the current `MSS` class directly.
6. **Medium — stale-at-dispatch retry.** A target ROI can legitimately change between step
   creation and gateway dispatch because of animation or a transient overlay. The gateway still
   fails closed, while the visual service now performs one fresh recapture/re-ground retry before
   surfacing failure. The real fixture reproduced and verified this path.

## Positive controls

The design has small adapters, typed schemas, bounded collections, explicit confidence states,
safe reason summaries, a single mutation gateway, deterministic fixtures, and clear separation
between observe and act. Local CV does not duplicate OCR/model infrastructure.

## Result

Open findings after remediation: Blocking 0, High 0, Medium 0. No style-only comments were used as
release gates.
