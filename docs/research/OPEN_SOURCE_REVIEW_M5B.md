# M5-B Open Source Review — Visual Desktop Intelligence

Date: 2026-08-10

Phase: M5-B

Policy: OPEN-SOURCE-FIRST / NO FULL FORK

## Capability boundary

M5-B needs local Windows screen capture, ephemeral image processing, deterministic visual
grounding, UI Automation fusion, privacy redaction, and governed visual-action validation. The
model must never receive a screenshot or a third-party click/execute primitive directly. All
observation and action paths remain behind AI Team OS governance, approval, budget, audit,
workspace, secret, memory, and security boundaries.

This review inspected project READMEs, architecture/source layout, licenses, releases, recent
activity, issues/security guidance, dependencies, examples, and tests. No repository will be
forked and no third-party source will be copied into AI Team OS.

## Candidate comparison

| Candidate | Fit | Activity / quality | Dependencies | Windows / Python 3.11 | Security / license | Performance / tests | Integration impact | Decision |
|---|---|---|---|---|---|---|---|---|
| [python-mss](https://github.com/BoboTiG/python-mss) | Full/monitor/region capture and monitor geometry | Active; 10.2.0 released 2026-04-23; compact ctypes backend, demos and tests | No runtime dependencies | Native Windows backend; Python 3.10+ | MIT; no network or external executable | Fast in-memory capture; multi-monitor examples/tests | Small adapter; DPI initialization order must be controlled | LEVEL 2 adapter, direct dependency |
| [Pillow](https://github.com/python-pillow/Pillow) | Window/region image handling, crop, mask, redact, overlay, encoding | Very active; 12.2.0 released 2026-04-01; mature core and extensive test suite | Self-contained wheels | Windows `ImageGrab` supports all screens and window handles; Python 3.11 supported | HPND/Pillow license; private vulnerability reporting | Mature C-backed image operations and broad tests | Small, already installed transitively; declare explicitly | LEVEL 1 direct dependency |
| [OpenCV](https://github.com/opencv/opencv) / [Python wheels](https://github.com/opencv/opencv-python) | Deterministic contour, template, colour and frame-diff operations | Very active; OpenCV 4.14.0 released 2026-07-19; mature algorithms and tests | Headless wheel contains native components, including FFmpeg notices | Official Windows wheels support Python 3.11 | OpenCV Apache-2.0; wheel packaging MIT; bundled third-party licenses must ship with distributions | High-performance C++ primitives; extensive upstream tests | Bounded local adapter; remain on stable 4.x API | LEVEL 1 direct dependency |
| [pywinauto](https://github.com/pywinauto/pywinauto) | Existing UIA tree, bounds, state and semantic actions | 0.6.9 released 2025-01-06; mature but slower release cadence; active maintenance concerns are visible in issues | Windows UIA/Win32 stack | Current M5-A Windows dependency works on Python 3.11 | BSD-3-Clause; UIA coverage varies by application | Established backend and tests, though test tooling is older | Already isolated by the M5-A backend; no new types may escape it | LEVEL 2 existing adapter retained |
| [DXcam](https://github.com/ra1nty/DXcam) | High-rate DXGI desktop capture | 0.3.0 released 2026-03-12; beta; small test surface | DXGI/WinRT/native wheel and ring buffer | Windows 10/11; Python 3.10–3.14 | MIT; persistent buffers increase lifecycle/privacy work | Excellent 240+ FPS use case, unnecessary for max 1 FPS M5-B | Higher native/GPU and cleanup complexity | LEVEL 4 architecture reference; rejected for M5-B dependency |
| [Tesseract](https://github.com/tesseract-ocr/tesseract) / [pytesseract](https://github.com/madmaze/pytesseract) | OCR fallback only | Tesseract is mature; Python wrapper release cadence is slower | External executable, Leptonica and language data; wrapper creates subprocesses | Windows install and language-pack burden | Apache-2.0; Leptonica BSD-2-Clause; executable/data supply chain must be governed | Strong OCR, but startup/ROI cost and external process surface | Conflicts with minimal local runtime and adds no value to required fixtures | LEVEL 4 bounded-ROI/timeout reference; rejected for M5-B |

## Detailed inspection and reuse decision

### python-mss

- **Repository / purpose:** [BoboTiG/python-mss](https://github.com/BoboTiG/python-mss), pure
  Python cross-platform screenshot capture using native APIs.
- **License:** [MIT](https://github.com/BoboTiG/python-mss/blob/main/LICENSE.txt), copyright and
  permission notice retained through dependency metadata.
- **Activity:** 10.2.0 on 2026-04-23, 44 releases and continuing commits at review time.
- **Inspected:** README, Windows backend under `src/mss/windows`, factory/base/models/screenshot
  modules, demos, tests, releases and issue surface.
- **Relevant components:** monitor enumeration, virtual-desktop coordinates, monitor and region
  grabs, in-memory pixel buffers, context-managed resource release.
- **Pros:** no runtime dependencies, strong multi-monitor fit, mature Windows implementation.
- **Cons:** does not capture a window by HWND and documents DPI-awareness import-order hazards.
- **Security:** no network and no executable launch; captured buffers must still be TTL-bound and
  must never be persisted by default.
- **Decision:** LEVEL 2 Adapter Integration backed by a direct dependency. Only internal image
  buffers and our own geometry types cross the adapter boundary.

### Pillow

- **Repository / purpose:** [python-pillow/Pillow](https://github.com/python-pillow/Pillow), mature
  imaging foundation.
- **License:** [HPND/Pillow](https://github.com/python-pillow/Pillow/blob/main/LICENSE), permissive
  with required notices.
- **Activity:** 12.2.0 on 2026-04-01, frequent maintenance and a large test suite.
- **Inspected:** README, license, security policy, releases, `src/PIL/ImageGrab.py`, image/crop/draw
  APIs and tests.
- **Relevant components:** Windows all-screen/window capture, crop, redact, resize, annotation and
  in-memory PNG encoding.
- **Pros:** already present in the environment, excellent interoperability, mature image safety
  fixes and tests.
- **Cons:** its window capture alone does not supply monitor metadata or semantic UI information.
- **Security:** keep decompression limits enabled; no untrusted image plugins are needed in M5-B.
- **Decision:** LEVEL 1 Direct Dependency, explicitly declared instead of relying on a transitive
  installation.

### OpenCV / opencv-python-headless

- **Repository / purpose:** [opencv/opencv](https://github.com/opencv/opencv) and official
  [Python wheel packaging](https://github.com/opencv/opencv-python), deterministic computer vision.
- **License:** OpenCV 4.5+ is
  [Apache-2.0](https://github.com/opencv/opencv/blob/4.x/LICENSE); wheel packaging is MIT and ships
  a third-party license inventory.
- **Activity:** active 4.x branch; 4.14.0 on 2026-07-19. OpenCV 5 exists, so M5-B stays below 5 to
  avoid an unnecessary major-version migration.
- **Inspected:** README, releases, security policy, license, wheel build configuration and license
  inventory, `modules/imgproc/src/templmatch.cpp`, image-processing tests and examples.
- **Relevant components:** contours, masks, connected components, template matching and absolute
  frame difference.
- **Pros:** high performance, well-tested algorithms, no need to invent image math.
- **Cons:** a large native wheel for a bounded feature set; bundled native-component notices must
  be preserved.
- **Security:** use the headless wheel, never video/network capture, never load arbitrary model
  weights, and bound image dimensions and operation time.
- **Decision:** LEVEL 1 Direct Dependency with an internal deterministic-CV adapter. No OpenCV
  matrix or contour types enter business models.

### pywinauto

- **Repository / purpose:** [pywinauto/pywinauto](https://github.com/pywinauto/pywinauto), Windows
  Win32/UIA automation.
- **License:** BSD-3-Clause since 0.6.0.
- **Activity:** current project dependency is 0.6.9; the project remains useful but has a visibly
  slower cadence and an [open maintenance discussion](https://github.com/pywinauto/pywinauto/issues/1397).
- **Inspected:** README, license/releases/issues, `uiawrapper.py`, interface wrappers, examples and
  tests.
- **Relevant components:** semantic control tree, automation IDs, bounds, state, invoke/value/
  selection interfaces.
- **Pros:** already integrated and validated in M5-A; prevents coordinates from becoming the
  primary control surface.
- **Cons:** UIA is absent or incomplete for canvas/custom-rendered controls and varies across apps.
- **Security:** action methods remain exclusively behind `WindowsActionGateway`; observation
  exposes a normalized allow-list, not arbitrary wrapper objects.
- **Decision:** LEVEL 2 Adapter Integration retained. M5-B fuses it with pixels rather than
  replacing it.

### Rejected candidates

- **DXcam:** its high-rate DXGI capture and ring-buffer architecture solve game/video workloads,
  while M5-B defaults to manual capture and caps auto-refresh at 1 FPS. The beta status, native GPU
  surface, and long-lived buffers add risk without product benefit. Resource-release and output
  enumeration patterns are LEVEL 4 references only.
- **Tesseract/pytesseract:** OCR is explicitly a fallback, and M5-B's acceptance fixture can be
  grounded using UIA plus deterministic local geometry. Adding an external executable,
  subprocess, language data, and another update channel would enlarge the security and packaging
  surface. ROI/confidence/timeout design is a LEVEL 4 reference for a future governed OCR adapter.

## Selected architecture

```text
LLM / user request
        |
AI Team OS governance (session, capability, risk, approval, budget, audit, privacy)
        |
DesktopObserver + ObservationFusion + VisualActionValidator
        |
internal adapters only
  |              |                 |
pywinauto UIA    MSS/Pillow        OpenCV headless
semantics        pixels/redaction  deterministic CV
```

- UIA remains first priority.
- UIA + local pixels is the normal fusion path.
- Vision-only grounding is allowed only when semantic UIA is absent and confidence is sufficient.
- Raw coordinates are the lowest-priority, explicitly governed fallback.
- Third-party capture/CV libraries cannot click, type, execute, approve, persist screenshots, or
  contact an external provider.

## WHY_CUSTOM_IMPLEMENTATION

Custom code is still required only for the product-specific gaps no reviewed library provides:

1. `DesktopObservation`, `VisionObservation`, `VisualElement`, and `VisualGrounding` contracts that
   do not leak third-party types.
2. Session-bound capture IDs, 60-second-or-shorter TTL, stop-time buffer clearing, and stale-capture
   invalidation.
3. UIA/pixel fusion priority, ambiguity handling, confidence policy, DPI/negative-coordinate
   transforms, and bounded re-grounding.
4. Password/credential-region redaction before any optional external-provider boundary.
5. `VisualActionValidator` checks against window, resolution, DPI, target, risk, approval, and
   current capture; after-action verification and two-attempt maximum.
6. Governance events, evidence, bilingual UI, target preview, and a default-off external-image
   consent gate.

These are governance and product semantics, not reimplementations of screen capture, UIA, imaging,
or computer-vision algorithms.

## License and supply-chain conclusion

- Permissive licenses selected: MIT (MSS), HPND/Pillow, Apache-2.0 (OpenCV), MIT (Python wheel
  packaging), BSD-3-Clause (pywinauto).
- No GPL/AGPL code, model weights, repository fork, or copied upstream source is introduced.
- The source and distribution notices for dependencies, including the OpenCV wheel's bundled
  third-party components, must remain available through dependency metadata and release notices.
- Runtime imports will be pinned to compatible major versions and checked by dependency/import
  tests. Capture adapters have no network path; external vision remains separately configurable
  and disabled by default.

## Avoided custom work

Estimated avoided implementation: 2,500–4,000 lines plus substantial Windows/DPI/native-wheel
debugging. The estimate covers monitor enumeration and capture, window image conversion, crop/
redact/encode primitives, UIA traversal/interfaces, and contour/template/frame-diff algorithms.
AI Team OS custom work stays concentrated on governance, fusion, safety, evidence, and UX.
