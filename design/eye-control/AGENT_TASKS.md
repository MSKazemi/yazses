# Agent-sized task catalogue — eye / camera control

This is the source text for GitHub child issues under #102. Issue numbers are populated after issue
creation. Each task is intentionally narrow enough to hand to a coding agent **together with the
linked ADR/roadmap section**.

## GitHub issue map

All tasks below are attached to milestone **Hands-free — perception & accessibility** (#10).

| Task | Issue |
|---|---:|
| EYE-DOC-001 | #392 |
| EYE-ARCH-001 | #393 |
| EYE-CAM-001 | #394 |
| EYE-CAM-002 | #395 |
| EYE-CAM-003 | #396 |
| EYE-GAZE-001 | #397 |
| EYE-GAZE-002 | #398 |
| EYE-MEASURE-001 | #399 |
| EYE-PTR-001 | #400 |
| EYE-PTR-002 | #401 |
| EYE-PTR-003 | #402 |
| EYE-PTR-004 | #403 |
| EYE-HEAD-001 | #404 |
| EYE-HEAD-002 | #405 |
| EYE-FACE-001 | #406 |
| EYE-FACE-002 | #407 |
| EYE-GESTURE-001 | #408 |
| EYE-BENCH-001 | #409 |
| EYE-BUNDLE-001 | #410 |
| EYE-HW-001 | #411 |
| EYE-TRACKER-001 | #412 |
| EYE-PERM-001 | #414 |
| EYE-DISPLAY-001 | #415 |
| EYE-OBS-001 | #416 |
| EYE-SAFETY-001 | #417 |
| EYE-WAYLAND-001 | #418 |
| EYE-ACCESS-001 | #419 |
| EYE-SETTINGS-001 | #420 |
| EYE-EVAL-001 | #421 |
| EYE-EVAL-002 | #422 |
| EYE-EVAL-003 | #423 |
| EYE-EVAL-CI-001 | #424 |
| EYE-PAPER-001 | #425 |
| EYE-PAPER-002 | #426 |
| EYE-CONSENT-001 | #427 |
| EYE-QA-WIN-A | #428 |
| EYE-QA-WIN-B | #429 |
| EYE-QA-MAC-A | #430 |
| EYE-QA-MAC-B | #431 |
| EYE-QA-GNOME-A | #432 |
| EYE-QA-GNOME-B | #433 |
| EYE-QA-KDE-A | #434 |
| EYE-QA-X11-A | #435 |
| EYE-QA-HIDPI-A | #436 |
| EYE-QA-REPEAT-A | #437 |
| EYE-QA-KDE-B | #438 |
| EYE-QA-X11-B | #439 |
| EYE-QA-HIDPI-B | #440 |

## How to use a task

A contributor or coding agent should:

1. read [README.md](README.md) and the task's prerequisite files;
2. inspect the named existing tests before editing;
3. change only the allowed-path area unless the issue explains why expansion is necessary;
4. add a failing test first for the contract being introduced/fixed;
5. run the narrow validation commands;
6. run the repository test/lint/type-check set when feasible;
7. report hardware evidence separately from CI evidence.

Do not solve a later task "while here". Small PRs are a design goal.

## Task inventory

| ID | Task | Risk | Typical size | Hardware for coding? | Depends on |
|---|---|---:|---:|---|---|
| EYE-DOC-001 | Correct stale Face-Gesture implementation claims | L1 | 30–45 min | no | none |
| EYE-ARCH-001 | Add pure shared perception signal contracts | L2 | 60–90 min | no | ADR-v2-135 |
| EYE-CAM-001 | Add one-owner camera/perception lifecycle | L2 | 90–150 min | no | EYE-ARCH-001 |
| EYE-CAM-002 | Emit gaze + head pose + blendshapes from one MediaPipe result | L3 | 2–3 h | no (fake MP) | EYE-CAM-001 |
| EYE-CAM-003 | Refactor existing gaze backend to consume shared perception | L3 | 2–3 h | no | EYE-CAM-002 |
| EYE-GAZE-001 | Runtime click/gaze sample capture for implicit calibration | L3 | 2–3 h | no for CI | EYE-CAM-003 |
| EYE-GAZE-002 | Apply/persist/rollback implicit calibration behind holdout gate | L2 | 90–150 min | no | EYE-GAZE-001 |
| EYE-MEASURE-001 | Add privacy-safe gaze field-measurement report for #104 | L2 | 90–150 min | no for coding; yes for evidence | EYE-CAM-003 |
| EYE-PTR-001 | Define PointerSink protocol + shared fake contract suite | L2 | 60–90 min | no | none |
| EYE-PTR-002 | Add X11 pointer sink | L2 | 60–120 min | no for CI | EYE-PTR-001 |
| EYE-PTR-003 | Add macOS + Windows pointer sinks behind platform abstraction | L3 | 2–3 h | no for CI | EYE-PTR-001 |
| EYE-PTR-004 | Extend existing XDG RemoteDesktop portal session for POINTER | L3 | 2–3 h | no for CI; Wayland for smoke | EYE-PTR-001 |
| EYE-HEAD-001 | Wire Head-Pointer runtime loop to shared pose + PointerSink | L3 | 2–3 h | no for CI | EYE-CAM-002 + one pointer sink |
| EYE-HEAD-002 | Add re-centre, pause/clutch and dwell-click feedback | L2 | 90–150 min | no for CI | EYE-HEAD-001 |
| EYE-FACE-001 | Pure calibrated/hysteretic face-switch detector | L2 | 90–150 min | no | EYE-CAM-002 |
| EYE-FACE-002 | Face-switch activation adapter + configurable action mapping | L3 | 2–3 h | no | EYE-FACE-001 |
| EYE-GESTURE-001 | Feed head/face tokens into existing Gesture Chords runtime | L2 | 90–150 min | no | EYE-FACE-002 |
| EYE-BENCH-001 | False-activation numeric trace harness + report template | L2 | 60–120 min | no for harness; yes for evidence | EYE-FACE-001 |
| EYE-BUNDLE-001 | Compose a hands-free preset from shipped components | L3 | 2–3 h | no for CI | head + face + pointer path |
| EYE-HW-001 | Run cross-hardware accessibility acceptance matrix | L1 research | 1–2 h/device | yes | experimental runtime available |
| EYE-TRACKER-001 | Dedicated eye-tracker API/licensing capability study | L1 research | 2–4 h | no | webcam programme stable |
| EYE-PERM-001 | Cross-platform camera permission + packaging contract | L2 | 2–3 h | no for CI | shared-perception design |
| EYE-DISPLAY-001 | Multi-monitor/HiDPI coordinate + calibration invalidation | L2 | 2–3 h | no | ADR-v2-139 |
| EYE-OBS-001 | Doctor/status observability for sensor/backend health | L2 | 90–150 min | no | signal/source state contracts |
| EYE-SAFETY-001 | Global pause/kill state + stale-signal watchdog | L2 | 2–3 h | no | ADR-v2-138 |
| EYE-WAYLAND-001 | Define honest gaze-target semantics on Wayland | L1 research/design | 2–4 h | Wayland for validation | gaze routing + portal research |
| EYE-ACCESS-001 | Accessibility co-design + fatigue/usability protocol | L1 research | multi-session | yes | experimental runtime |
| EYE-SETTINGS-001 | Accessible settings/recovery surface for hands-free controls | L3 | 2–4 h | no for CI | config + observability stable |

## Detailed contracts

### EYE-DOC-001 — correct stale Face-Gesture implementation claims

**Problem:** `docs/store-submission.md`, the MSIX manifest comment and its test say the
Face-Gesture adapter already exists/works. Repository search shows no runtime implementation.

**Allowed paths**
- `docs/store-submission.md`
- `packaging/windows/msix/AppxManifest.xml`
- `tests/test_msix_manifest.py`

**Done when**
- text says gaze is implemented;
- Face-Gesture is clearly planned/experimental, not currently reachable;
- webcam-capability rationale remains correct for the frozen MSIX;
- manifest tests still pass.

**Validate**
```sh
uv run python -m pytest tests/test_msix_manifest.py -q
```

### EYE-ARCH-001 — pure signal contracts

Create dependency-free dataclasses/protocols for derived camera signals.

**Allowed paths**
- a new small module under `src/yazses/perception/`
- focused tests under `tests/`

**Must not**
- import cv2/mediapipe;
- own a thread;
- open a camera;
- include raw frame fields.

**Tests**
- immutable/value semantics;
- optional/missing signals;
- confidence/time validation if implemented.

### EYE-CAM-001 — single camera owner

Implement the source lifecycle using injected capture/processor seams.

**Acceptance**
- one open for N consumers;
- close after final consumer;
- start/stop idempotent;
- disabled means zero imports/probes/opens;
- failure is contained;
- unit tests use fakes.

### EYE-CAM-002 — one MediaPipe result -> three signal families

Upgrade FaceLandmarker options to emit blendshapes and facial transform data while preserving gaze
landmarks.

**Acceptance**
- fake MediaPipe result produces deterministic gaze/head/face derived values;
- no second FaceLandmarker;
- no behavior regression in existing gaze tests;
- missing transform/blendshape degrades per-channel, not whole-source crash.

### EYE-CAM-003 — migrate gaze without changing semantics

Adapt `GazeTargeter`/backend path to shared gaze samples.

**Acceptance**
- existing `test_gaze_*.py` suites remain green;
- confidence threshold and focused-window fallback unchanged;
- camera lifetime now belongs to shared source;
- public config compatibility retained.

### EYE-GAZE-001 — runtime implicit-calibration capture

Wire click observations to timestamped gaze without putting OS hooks in `implicit.py`.

**Acceptance**
- pure click-observer protocol/fake;
- configurable look-back/association window;
- rejects missing/low-confidence samples;
- capture is opt-in;
- tests prove no storage of images/text.

### EYE-GAZE-002 — apply refined map safely

Use existing `refined_if_better` and calibration store.

**Acceptance**
- baseline persists until candidate wins held-out evaluation;
- failed/worse candidate leaves bytes/state unchanged;
- status identifies active calibration source;
- rollback is tested.

### EYE-MEASURE-001 — field evidence for #104

Add a command/report helper that produces derived metrics suitable for attaching to #104.

**Never export:** frames, face mesh, screenshots, transcript or window titles by default.

**Test:** golden schema + privacy assertions + empty/partial session.

### EYE-PTR-001 — PointerSink

Create the smallest platform-independent pointer output contract and common behavior tests.

**Acceptance**
- fake records motion/click/scroll;
- unsupported capabilities explicit;
- no camera/headpointer imports;
- no shell commands in the protocol module.

### EYE-PTR-002 / 003 / 004 — one backend per PR

Implement exactly one platform family in each PR. Reuse existing platform/injection mechanisms.

For Wayland, extend `src/yazses/inject/portal.py`; do not create a parallel D-Bus session.

### EYE-HEAD-001 — runtime head pointer

Reference `WIRE-HEADPOINTER-001`.

**Acceptance**
- shared HeadPoseSignal -> existing `pose_to_cursor`;
- move via PointerSink;
- dwell via existing `DwellClicker`;
- signal loss stops;
- feature enable becomes truthfully reachable only when enough backend capability exists;
- update feature-registry wiring honesty tests.

### EYE-HEAD-002 — control/recovery UX

Add recenter, pause and dwell feedback. No feature should trap a user behind a moving pointer.

**Acceptance**
- pause suppresses movement and click;
- re-centre changes neutral reference;
- dwell progress is observable before firing;
- startup/signal recovery cannot immediately click.

### EYE-FACE-001 — deliberate face switch detector

Pure numeric algorithm over blendshapes.

**Acceptance**
- neutral baseline;
- enter/exit hysteresis;
- min-hold;
- refractory period;
- confidence gate;
- one event per gesture;
- fixture traces cover ordinary blink, talking-like mouth movement and deliberate action.

Do not label any gesture "recommended" from synthetic tests.

### EYE-FACE-002 — activation adapter

Map detector event -> abstract switch/activation event.

**Acceptance**
- detector has no knowledge of daemon actions;
- mapping configuration validated;
- destructive action passes existing confirmation policy;
- unmapped/unknown gesture does nothing;
- can freeze head-pointer motion during commit gesture.

### EYE-GESTURE-001 — chord runtime

Reference `WIRE-GESTURE-001`.

Feed abstract head/face tokens to the existing input-agnostic chord resolver. Do not duplicate chord
logic.

### EYE-BENCH-001 — false activations

Build trace runner that reports:
- intended activations;
- detected activations;
- misses;
- false activations;
- false activations/hour where duration is known.

No photos required.

### EYE-BUNDLE-001 — hands-free preset

Preset only; no new parallel pipeline.

**Acceptance**
- expands into existing feature configs;
- one disable action stops pointer/switch/camera consumers;
- `doctor` can list unavailable prerequisites;
- docs show at least one "speech + head pointer + face switch" workflow and fallback.

### EYE-HW-001 — acceptance matrix

Use [TEST_PLAN.md](TEST_PLAN.md). Contributors report environment + derived metrics. Negative results
are valid.

### EYE-TRACKER-001 — dedicated tracker study

Output a short design note comparing APIs/licensing across target OSes. No vendor SDK is added in
this task.


## Cross-cutting production tasks

These tasks are **release obligations**, not extra features.

### EYE-PERM-001 — permissions and packaging

Issue #414. Ensure camera permission/capability matches what each install format can actually run.
Ordinary dictation must survive permission denial.

### EYE-DISPLAY-001 — multi-monitor / HiDPI / invalidation

Issue #415. Implements ADR-v2-139 so calibration cannot silently survive an incompatible display or
camera topology.

### EYE-OBS-001 — observability

Issue #416. Add privacy-safe camera/perception/head/face/pointer health to doctor/status.

### EYE-SAFETY-001 — global stop and stale-signal watchdog

Issue #417. One ACTIVE/PAUSED/FAULTED safety state suppresses continuous actions and prevents stale
pose/switch replay.

### EYE-WAYLAND-001 — gaze targeting semantics

Issue #418. Research/design first: pointer portal capability is not the same thing as permission to
focus a gaze-selected window.

### EYE-ACCESS-001 — co-design and fatigue evidence

Issue #419. Required before recommended defaults. Negative results stay in the record.

### EYE-SETTINGS-001 — usable control surface

Issue #420. Expose enable/pause/recenter/dwell/switch mapping/calibration/status in the existing
settings system once the underlying contracts stabilize.


## Evaluation and evidence tasks

These tasks make the programme measurable without turning public GitHub testing into accidental human
research.

| Task | What it produces | Contributor type | Hardware |
|---|---|---|---|
| #421 EYE-EVAL-001 | Versioned result JSON schema + validator | Python / agent-ready | no |
| #422 EYE-EVAL-002 | Deterministic gaze/pointer/face test fixtures | Python / agent-ready | no |
| #423 EYE-EVAL-003 | Local privacy-safe evaluation runner/exporter | Python / agent-ready | no for CI |
| #424 EYE-EVAL-CI-001 | Windows/macOS/Linux non-hardware CI matrix | CI / Python | hosted runners |
| #425 EYE-PAPER-001 | Frozen human-study + ethics/preregistration plan | research/design | no |
| #426 EYE-PAPER-002 | Reproducible de-identified analysis pipeline | Python/research | no |
| #427 EYE-CONSENT-001 | Plain-language data-sharing review | documentation | no |

### No-code hardware validation slots

Each issue below is intentionally one small contribution: **one tester, one computer, one scripted
report** unless the issue says otherwise. Public reports are engineering QA, not paper consent.

| Issue | Environment | Why it exists |
|---|---|---|
| #428 | Windows 11 A | first independent Windows host |
| #429 | Windows 11 B | different computer/person replication |
| #430 | macOS Apple Silicon A | first independent Mac host |
| #431 | macOS Apple Silicon B | different computer/person replication |
| #432 | Ubuntu/GNOME Wayland A | first GNOME/Wayland host |
| #433 | Ubuntu/GNOME Wayland B | different computer/person replication |
| #434 | KDE Plasma Wayland | compositor/portal variation |
| #435 | Linux X11 | existing gaze/pointer path |
| #436 | HiDPI / multi-monitor | coordinate + calibration topology |
| #437 | same person/computer x3 sessions | test-retest drift/stability |
| #438 | KDE Plasma Wayland B | different computer/person replication |
| #439 | Linux X11 B | different computer/person replication |
| #440 | HiDPI / multi-monitor B | different topology/computer replication |

All no-code slots are `good first issue`, `measurement-wanted`, and `hardware-required`.
A reproducible FAIL/PARTIAL/BLOCKED result is a valid completed contribution.
