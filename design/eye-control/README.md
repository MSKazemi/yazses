# Eye / camera control programme

**Status:** active planning record  
**Audit date:** 2026-09-22  
**Parent delivery epic:** [#102 — hands-free bundle](https://github.com/MSKazemi/yazses/issues/102)  
**Planning-traceability epic:** [#377](https://github.com/MSKazemi/yazses/issues/377)  
**Milestone:** `Hands-free — perception & accessibility` (#10)

This directory is the canonical implementation map for eye-, head-, and face-camera control in YazSes.
It exists because the repository already contains substantial gaze and hands-free work, but that work
was spread across research pages, ADRs, pure cores, runtime code, one large epic, and generic wiring
tasks. A contributor should not have to rediscover which pieces are real before changing them.

The programme is intentionally broader than "eye tracking". A normal laptop camera can provide
several useful **coarse** signals:

- gaze direction — good for choosing a pane/window, not a text caret;
- head pose — good for continuous pointer movement;
- deliberate facial expressions — good as switch/commit inputs;
- face presence/quality — useful for confidence and safe fallback.

These signals serve different jobs. They must not be collapsed into one magic "camera controls the
computer" feature.

## Product position

YazSes should become a **multimodal hands-free desktop control layer** where each modality does the
job it is strongest at:

| Job | Preferred modality | Why |
|---|---|---|
| Generate text | speech | fast, high bandwidth |
| Choose which pane/window receives text | webcam gaze | coarse spatial context is enough |
| Resolve "this / that window" | gaze + speech | gaze grounds; speech states intent |
| Move a mouse pointer continuously | head pose | stable continuous signal without pretending webcam gaze is precise |
| Commit/select without a hand | deliberate face gesture, dwell, voice, or EMG switch | explicit intent channel |
| Precision gaze pointer | dedicated eye tracker, future optional backend | dedicated IR hardware is materially more accurate |
| Recovery when camera confidence is low | current focus, voice mouse grid, keyboard/switch | safe degradation instead of fake precision |

The default interaction principle is:

> **Perception proposes; an intent-bearing action commits.**

That preserves the Midas-touch lesson already documented in YazSes research: eyes are always looking
somewhere, therefore gaze alone should not silently execute arbitrary desktop actions.

## User-facing use cases

### UC-1 — Glance-Type: look to a pane, then dictate

Already shipped on X11. At hold start, YazSes samples gaze, maps it through the user's calibration,
finds the looked-at window, and routes the next dictation there. Low-confidence gaze falls back to
the already-focused window.

**Target:** harden rather than redesign this path.

### UC-2 — Point-and-speak: "close this", "focus that"

Already shipped. A gaze snapshot grounds a spoken demonstrative. Destructive operations use the
existing confirmation path.

**Target:** preserve the "gaze grounds, speech commits" model as the safest high-value use of webcam
gaze.

### UC-3 — Head pointer: move the pointer without hands

The pure math exists but the runtime does not. Head yaw/pitch should drive relative pointer motion.
A dead zone suppresses jitter. A dwell state machine may click, but the user must be able to pause
pointer motion and disable dwell independently.

**Target:** a real cross-platform pointer mode built on the existing `headpointer` core.

### UC-4 — Face-gesture switch: deliberate expression as a button

Use MediaPipe blendshapes to detect deliberate expressions such as **open mouth** or **raise
eyebrows** after a short neutral calibration. Convert the detector output into an abstract switch
token. The token may start/stop dictation, click, confirm, cancel, pause the pointer, or participate
in an existing Gesture Chord.

Natural blinking must **not** be the default click/commit gesture. Blink can remain an opt-in
advanced mapping only after false-activation measurement.

### UC-5 — Dwell-to-talk / dwell-to-select

For a user who cannot reliably produce a discrete switch, dwell can provide a fallback commit. It
should initially be limited to an explicit activation target or a pointer that the user can pause,
not "stare anywhere on the desktop and click".

### UC-6 — Dedicated eye tracker mode

Windows Eye Control and commercial AAC systems demonstrate the value of dedicated IR eye trackers.
YazSes should eventually expose a small `GazeSampleProvider` protocol so a Tobii-compatible or
other tracker can replace webcam gaze without changing routing, deixis, or safety policy.

This is **not** an immediate dependency for the webcam programme.

## State-of-the-art snapshot (2026-09-22)

This is a product/architecture refresh, not a replacement for
[`docs/research/eye-control.md`](../../docs/research/eye-control.md), which contains the
peer-reviewed gaze-accuracy evidence.

### Apple: separate pointer, snapping, dwell and commit controls

Current iPad Eye Tracking uses the built-in front camera, performs calibration, supports smoothing,
snap-to-item, keyboard zoom, auto-hide and dwell, and processes setup/control data on device. It can
also accept external MFi eye trackers.

Current iPhone/iPad Head Tracking uses the front camera for a head-driven pointer and lets users map
facial expressions such as **Raise Eyebrows** and **Open Mouth** to actions, with separate sensitivity,
pointer speed, snap-to-item and dwell settings.

Design lesson for YazSes: pointer movement, target snapping, gesture commit, dwell and calibration
are distinct controls and should remain independently configurable.

Sources:
- https://support.apple.com/guide/ipad/control-ipad-with-the-movement-of-your-eyes-ipad2cd35723/ipados
- https://support.apple.com/guide/iphone/control-iphone-with-the-movement-of-your-head-iph9c3dc17cf/ios

### Windows: mature eye control, but with dedicated tracking hardware

Windows Eye Control provides launchpad, mouse, precise mouse, scrolling, keyboard and text-to-speech,
but Microsoft's supported setup still expects a dedicated eye-tracking device such as supported
Tobii/EyeTech hardware or an integrated tracker.

Design lesson: do not claim a laptop webcam has dedicated-tracker precision. Keep webcam gaze in the
coarse target-selection role; reserve precise pointer control for head pose or future dedicated
tracker backends.

Source:
- https://support.microsoft.com/en-us/accessibility/windows/eye-control/get-started-with-eye-control-in-windows

### Google Project Gameface: strong precedent, no longer an active upstream

Project Gameface demonstrated webcam head movement plus facial gestures for mouse control on Windows
and Android using MediaPipe. The repository was archived on 2025-09-05. Its public issue history also
shows an important engineering failure mode: facial gestures and head motion can couple, making the
pointer jump while a gesture is being performed.

Design lesson: derive **independent signal channels** from one face inference result and allow
pointer motion to freeze while a commit gesture is active.

Source:
- https://github.com/google/project-gameface

### MediaPipe Face Landmarker: one inference can serve all three camera capabilities

The current Face Landmarker API supports live-stream mode and can output:

- face landmarks;
- 52 face blendshape coefficients;
- facial transformation matrices.

YazSes already uses the same FaceLandmarker family for webcam gaze. The missing architectural step is
to make that inference a shared source instead of making future camera capabilities open and process
the same webcam independently.

Sources:
- https://ai.google.dev/edge/api/mediapipe/python/mp/tasks/vision/FaceLandmarkerOptions
- https://ai.google.dev/edge/api/mediapipe/python/mp/tasks/vision/drawing_styles/face_landmarker/Blendshapes

### Wayland: pointer injection is now a concrete path, not a research placeholder

YazSes already owns an XDG RemoteDesktop portal session implementation for Wayland keyboard injection
in `src/yazses/inject/portal.py`. The portal API also supports relative/absolute pointer motion,
buttons and axes when POINTER access is granted. `libei` / `liboeffis` are the lower-level
Wayland-oriented equivalents.

Design lesson: extend the existing YazSes portal session to pointer capability before adding a new
Wayland-specific automation stack.

Sources:
- https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.RemoteDesktop.html
- https://libinput.pages.freedesktop.org/libei/api/index.html

### Dedicated tracker accuracy remains a different class

For scale, Tobii currently specifies Pro Spark at 0.45° accuracy and 0.26° RMS precision under
optimal conditions. That is materially different from commodity-webcam gaze. YazSes should expose a
future dedicated-tracker seam without letting those numbers leak into webcam claims.

Source:
- https://www.tobii.com/products/eye-trackers/screen-based/tobii-pro-spark

## As-built repository audit

Status vocabulary in this programme:

- **LIVE** — reachable from a current entry point and covered by runtime/wiring tests.
- **CORE** — useful production-quality pure core exists and is tested, but no complete runtime path.
- **DESIGNED** — accepted ADR/spec exists, but required implementation is absent.
- **RESEARCH** — evidence/question exists; no delivery commitment yet.

| Capability | Status | Evidence in repository | Missing work |
|---|---|---|---|
| Webcam gaze capture (MediaPipe) | **LIVE** | `gaze/mediapipe_backend.py`, factory, daemon wiring | shared-camera refactor; hardware breadth |
| L2CS gaze backend | **LIVE / optional** | `gaze/l2cs.py`, tests | keep optional; licensing/model caveats |
| 9-point calibration + persistence | **LIVE** | `gaze/calibrate.py`, `gaze/store.py`, CLI/tests | UX/field validation |
| Eye-agreement confidence | **LIVE** | `gaze/confidence.py`, MediaPipe tests | validate proxy against ground truth |
| Look-to-window routing | **LIVE (X11)** | `gaze/targeter.py`, `gaze/desktop.py`, daemon | Wayland target semantics; field error rate |
| Gaze + speech deixis | **LIVE** | `gaze/deixis.py`, daemon, confirmation tests | hardware validation |
| Implicit calibration estimator | **CORE** | `gaze/implicit.py`, `test_gaze_implicit.py` | runtime click capture + apply/persist path |
| Head pose → cursor math | **CORE** | `headpointer/pointer.py` | camera pose source + pointer sink + runtime loop |
| Dwell click state machine | **CORE** | `headpointer/pointer.py` | runtime feedback, pause/clutch, pointer sink |
| Gesture chord resolver | **CORE** | `gesture/chords.py` | sensor tokens + runtime wiring |
| Face-gesture switch detector | **DESIGNED** | #102 / ADR references only | detector, calibration, debounce, activation adapter |
| Shared camera/perception source | **DESIGNED by this programme** | proposed ADR-v2-135 | protocol + lifecycle + refactor |
| Wayland pointer injection | **PARTIAL** | keyboard portal exists | request POINTER, emit motion/buttons, tests |
| Dedicated eye tracker backend | **RESEARCH** | eye-control research | provider protocol + licensing/device study |
| Hands-free bundle/profile | **DESIGNED** | #102 + research directions | compose features into one usable mode |

### Important planning corrections

1. **Issue #101 is closed, but only the pure implicit-calibration estimator is present.**
   The issue body described click capture and runtime refinement too. New child work must cover that
   remaining wiring instead of treating implicit calibration as fully delivered.
2. **`headpointer` and `gesture` already have generic campaign tasks**
   (`WIRE-HEADPOINTER-001`, `WIRE-GESTURE-001`) under #164. New issues should refine those tasks
   and satisfy them, not create a second competing implementation.
3. **Some Windows packaging text says a Face-Gesture adapter already works.**
   Repository search found no implementation class/module for that adapter. This wording is stale and
   must be corrected until the new face-switch work lands.
4. **Wayland is less blank than #102 suggests.** Keyboard RemoteDesktop portal code is already
   substantial; pointer support should extend that session.

## Existing ADRs that remain authoritative

- [ADR-v2-010 — Gaze-Routed Dictation & Point-and-Speak](../adr/adr-v2-010-gaze-routed-dictation.md)
- [ADR-v2-043 — Gesture Chords](../adr/adr-v2-043-gesture-chords.md)
- [ADR-v2-052 — Head-Pointer](../adr/adr-v2-052-head-pointer.md)
- [ADR-011 — privacy / local camera handling](../adr/adr-011.md)
- [ADR-014 — held-out validation](../adr/adr-014-tune-holdout-validation.md)
- [ADR-v2-129 — killer features follow-up list](../adr/adr-v2-129-killer-features-10x.md)
- [ADR-v2-135 — shared camera perception](../adr/adr-v2-135-shared-camera-perception.md)
- [ADR-v2-136 — pointer-output boundary](../adr/adr-v2-136-pointer-output-boundary.md)
- [ADR-v2-137 — face gesture emits switch intent](../adr/adr-v2-137-face-switch-intent.md)
- [ADR-v2-138 — hands-free composition + global safety state](../adr/adr-v2-138-hands-free-composition.md)
- [ADR-v2-139 — calibration coordinate space/topology](../adr/adr-v2-139-gaze-calibration-coordinate-space.md)

ADR-v2-135 and the follow-on programme ADRs do **not** replace those
decisions. It defines the missing shared camera seam beneath them.

## Non-goals

This programme does not:

- promise caret-level webcam gaze;
- infer identity, emotion, health, attention, or cognitive state from a face;
- store raw camera frames in the learning corpus;
- make blink the default click;
- silently execute destructive actions from a noisy sensor;
- add a cloud vision API;
- require camera dependencies for users who do not enable a camera feature;
- replace voice with a slow gaze keyboard when speech is usable.

## Definition of "eye support is clear"

Eye/camera support is considered planning-complete when every active item has this trace:

```
research / use case
  -> ADR or explicit design rule
  -> current status (LIVE / CORE / DESIGNED / RESEARCH)
  -> one bounded GitHub issue
  -> milestone
  -> code + tests
  -> hardware evidence where hardware matters
```

See the programme set:
- [ROADMAP.md](ROADMAP.md) — dependency-ordered delivery;
- [GOVERNANCE.md](GOVERNANCE.md) — artifact/release gates and label policy;
- [TRACEABILITY.md](TRACEABILITY.md) — ADR -> spec -> issue -> verification;
- [RISK_REGISTER.md](RISK_REGISTER.md) — safety/reliability risks and blockers;
- [TEST_PLAN.md](TEST_PLAN.md) — hermetic and hardware validation;
- [AGENT_TASKS.md](AGENT_TASKS.md) — issue/task catalogue;
- [CONTRIBUTING.md](CONTRIBUTING.md) — contributor + coding-agent workflow;
- [EVALUATION.md](EVALUATION.md) — automated, hardware, cross-person and repeated-session evaluation ladder;
- [METRICS.md](METRICS.md) — canonical machine-readable parameters/metrics;
- [DATA_SHARING.md](DATA_SHARING.md) — public QA vs research consent/data-use rules;
- [PAPER_EVIDENCE.md](PAPER_EVIDENCE.md) — paper-quality study/data plan;
- [RESEARCH_PARTICIPANT_TEMPLATE.md](RESEARCH_PARTICIPANT_TEMPLATE.md) — pre-recruitment information/consent template.
