# M6-A Code Review

Date: 2026-08-12
Scope: M6-A diff only
Review count: 1

## Summary

The implementation preserves the existing governance boundaries and adds focused adapters instead
of replacing the runtime. The strongest parts are explicit WAITING states, no silent fallback,
SecretStore isolation, final-only transcript execution, bounded audio/session memory, and direct
reuse of the existing budget, approval, Windows and evidence layers.

## Findings resolved during this review

1. **High — STOP could wait behind a blocking Supervisor call.** `submit_final` originally held the
   voice state lock across the full model task. The external Supervisor call now runs outside the
   state lock, and the visible STOP endpoint invokes Computer Control emergency stop before ending
   the voice session.
2. **High — Voice desktop requests initially entered the generic task runtime only.** The voice
   Supervisor now requires an explicit configured Supervisor slot and routes recognized desktop
   actions through the existing Windows task planner/action gateway. Screen questions can attach a
   governed local observation when Computer Control is active.
3. **Medium — Role cost budgets were displayed but not enforced.** The routed provider now checks
   cumulative role spend and the provider's pre-call estimate. Unknown cost fails closed when a role
   cost budget is configured.
4. **Medium — Device disconnect returned a generic error.** It now enters `paused`, reports
   `DEVICE_UNAVAILABLE`, performs no model/action call, and permits device reselection/resume.
5. **Medium — VAD was an adapter but not in the execution path.** Silero ONNX now gates captured
   audio and supplies wake-utterance endpoint detection. Silence produces `NO_SPEECH` and no ASR or
   model call.
6. **Low — The fixed language switch covered a page-header action.** Main content now starts below
   the fixed control; browser acceptance confirmed the settings path remains clickable.
7. **Medium — Streaming transcript UI was not fed by local capture.** PTT and wake capture now run
   a bounded 0.8-second repeated-window preview worker. Preview text is display-only and the tests
   prove it makes no Supervisor or action call.
8. **Medium — Completed Supervisor responses did not automatically reach TTS.** The final text is
   now committed to the turn before asynchronous SAPI playback. TTS failure is logged as metadata
   but cannot convert the completed task into a failure; completion returns safely to idle.
9. **Medium — Conversation timeout was configurable but not active.** A cancellable daemon timer
   now closes an idle conversation after the configured interval and is cancelled by PTT, pause,
   STOP, or session shutdown.

## Verification

- Ruff and mypy pass for the complete backend.
- GT-MP01..12 and GT-VOICE01..16 deterministic suites pass.
- Full backend and frontend regressions pass.
- Browser ref-based acceptance covered routing, WAITING results, microphone settings, PTT, safe
  error, pause/resume, and STOP.

## Remaining non-blocking concerns

- Higher-quality ASR models need a separate size/quality product decision; Whisper tiny is an
  integration model, not the recommended Chinese production model.
- Native provider SDK adapters remain a future addition; M6-A supports the existing compatible
  adapter and does not fabricate unavailable provider protocols.
- Speaker verification is deliberately out of scope. Wake remains default OFF and experimental.

Final review result: **no open Blocker, High, Medium, or Low code defect in the reviewed M6-A diff**.
