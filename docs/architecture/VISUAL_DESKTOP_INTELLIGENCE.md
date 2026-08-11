# M5-B Visual Desktop Intelligence

## Outcome

M5-B adds a session-scoped visual desktop layer without replacing M5-A. Accessibility remains
the preferred identity and action mechanism; local deterministic vision contributes layout,
colour, icon, and change evidence; raw coordinates are a governed last resort.

```text
Screen capture + window metadata + UI Automation + bounded local CV
                              ↓
                    DesktopObservation
                              ↓
                 GroundingResolver (no action)
                              ↓
                    VisualGrounding
                              ↓
            VisualActionValidator → WindowsActionGateway
                              ↓
                    re-observe + verify
```

## Components

- `ScreenCaptureService`: MSS multi-monitor/full-screen/region capture and Pillow HWND capture,
  physical Windows coordinates, in-process storage, 45-second TTL, and stop-time clearing.
- `AccessibilityObserver`: bounded UIA metadata without secure values.
- `LocalVisualAnalyzer`: OpenCV colour/contour assistance only; no OCR, model weights, network, or
  instruction following.
- `ObservationFusion`: merges overlapping UIA and pixels while preserving UIA identity.
- `DesktopObserver`: builds the normalized desktop observation and marks screen content untrusted.
- `VisionCapabilityRegistry`: separates text and image capability, provider adapter, verified image
  support, user consent, and the external-processing gate.
- `GroundingResolver`: text, semantic, spatial, and ordinal hints; high/medium/low thresholds; safe
  ambiguity handling; no direct coordinate action.
- `VisualActionValidator`: validates session, capture freshness, window identity/bounds, DPI,
  target existence, sensitive regions, confidence, risk, and approval.
- `ScreenChangeDetector`: bounded pixel-difference verification after an action.
- `ScreenContextBuilder`: exposes a maximum of 40 relevant elements and 1,200 text characters as
  `UNTRUSTED_SCREEN_OBSERVATION`; screen questions always produce zero actions.

## Action order and lifecycle

The fixed action preference is UI Automation, UIA/vision fusion, vision-only grounding, then raw
coordinates. A visual action performs initial validation, a quick recapture, deterministic
re-grounding, final validation, gateway execution, after-capture, and change verification. A
second attempt is the hard maximum; unchanged state returns `ACTION_VERIFICATION_FAILED`.

A newer capture invalidates an older grounding by default. Short references such as “it” or “刚才
那个按钮” can use the most recent resolved grounding only inside the current control session and
still pass through fresh grounding and validation.

## Provider boundary

`VisionProvider` is a protocol rather than a model role. Provider output is treated as untrusted
pixel interpretation: it cannot supply an Accessibility identity, cannot return elements outside
the captured region, and is capped at 120 elements. Provider failures are converted to safe error
codes. Current status is:

```text
TEXT_MODEL = REAL (DeepSeek Official / deepseek-v4-flash)
MULTIMODAL_VISION_MODEL = NOT_CONFIGURED
DESKTOP_VISUAL_LAYER = VALIDATED
```

External processing is therefore disabled. Local Accessibility + deterministic CV remains fully
available.

## Coordinate system

MSS, Win32 window bounds, UIA bounds, and gateway clicks use physical screen coordinates. The
implementation supports virtual-screen negative origins and captures per-window DPI metadata.
Deterministic transforms cover 100%, 125%, and 150%; every action rechecks the current DPI and
window bounds. No 1920×1080 assumption exists.
