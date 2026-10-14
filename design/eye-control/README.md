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

## Start here

Choose the shortest document for your question:

| Question | Read |
|---|---|
| What exists today? | the **as-built audit** table below |
| What is READY or blocked? | the issues under [#102](https://github.com/MSKazemi/yazses/issues/102) — their banners and labels, never a file in this directory |
| I want to implement one small task | [AGENT_TASKS.md](AGENT_TASKS.md) |
| I am a beginner / no-code tester | [BEGINNER_TESTING.md](BEGINNER_TESTING.md) |
| What is the dependency-ordered roadmap? | [ROADMAP.md](ROADMAP.md) |
| How do we test across CI / OS / people? | [EVALUATION.md](EVALUATION.md) + [VALIDATION_MATRIX.md](VALIDATION_MATRIX.md) |
| What data/metrics do we collect? | [METRICS.md](METRICS.md) |
| What may a public tester share? | [DATA_SHARING.md](DATA_SHARING.md) |
| What evidence could support a paper? | [PAPER_EVIDENCE.md](PAPER_EVIDENCE.md) |
| What is the release/safety gate? | [GOVERNANCE.md](GOVERNANCE.md) + [RISK_REGISTER.md](RISK_REGISTER.md) |

**Do not infer issue readiness from this README.** The live issue banner + labels are authoritative.
An open issue without `help wanted` may be intentionally PLANNED.

**There is deliberately no status page here.** An earlier revision of this programme carried a
`STATUS.md` snapshot listing which issues were READY. It was wrong within two days — the one task
it named as the ready Wave-0 item had already been closed — which is the general case, not bad
luck: a file cannot track state that lives on GitHub. Readiness is read from the issues; this
directory holds only what stays true between releases. Snapshots of a moment belong in a working
note, not in `design/`.

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

**Shipped, in part.** ADR-v2-135 already turns one MediaPipe blendshape into a held hotkey
(`jaw_open` by default, with `brow_raise`, `mouth_pucker`, `smile` and an opt-in `eyes_closed`),
with separate hold/release thresholds and a frame-count debounce. What is described below and is
*not* built is the abstraction: the detector drives the dictation start/stop callbacks directly, so
the gesture cannot yet click, confirm, cancel, pause the pointer, or enter a Gesture Chord.

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

### UC-7 — Grounded target resolution: look roughly, act semantically

The 2026 Google Magic Pointer / Apple Siri AI research does not change the webcam accuracy ceiling.
It changes **where precision should come from**.

A coarse gaze/mouse/head target should identify the plausible region; accessibility/application
semantics should identify the exact UI entity; voice should state the operation. The proposed
ADR-v2-151 and [grounded-target spec](../specs/eye-grounded-targets.md) add that missing seam without
turning gaze into a fake high-precision cursor.

Initial scope is semantic-first and screenshot-free:

```text
coarse target -> structured UI candidates -> grounded / ambiguous / unresolved
             + spoken intent hint          -> planner -> safety -> action
```

OCR/VLM fallback is deliberately deferred until [the evaluation plan](GROUNDED_INTERACTION_RESEARCH.md)
measures a real semantic gap.

**Delivery:** #441–#445. This extension does not block the original head/face hands-free bundle.

## State-of-the-art snapshot (2026-09-22)

This is a product/architecture refresh, not a replacement for
[`docs/research/eye-control.md`](../../docs/research/eye-control.md), which contains the
peer-reviewed gaze-accuracy evidence.

### Google + Apple: grounding is becoming a system interaction layer

Google Magic Pointer and Apple's Siri AI / onscreen-awareness APIs converge on the same HCI split:
pointing says **which thing**, language says **what to do**, and a semantic layer resolves the exact
entity. For YazSes the practical lesson is semantic refinement, not screenshot-first automation.

See the cited public synthesis:
[Grounded multimodal interaction](../../docs/research/grounded-multimodal-interaction.md).

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
| Implicit calibration (click capture, held-out gate, atomic apply + rollback) | **CORE** | `gaze/implicit.py`, `gaze/clicks.py`, `gaze/refine.py`, `gaze/refine_runtime.py`, `[gaze_refine]`, `yazses gaze rollback` (#397, #398) | a real OS click observer: `Platform.click_observer_factory` is `None` on every OS, so the runtime stays dormant and logs why |
| Gaze field-measurement report | **LIVE (CLI)** | `yazses gaze measure`, golden-file test (#399) | tester reports on real hardware (#104) |
| Head pose → cursor runtime | **LIVE (X11, macOS, Windows; Wayland via portal, untested live; opt-in)** | `headpointer/controller.py`, `headpointer/runtime.py`, `[headpointer]`, `yazses headpointer ...` (#404) | real-hardware validation of a *driven* pointer, including the first real GNOME consent dialog; the x sign is fixed (2026-10-13, one webcam: left turn = +yaw, so `x_gain` is negative); gains are now per second with speed caps (`max_speed_*`) but every magnitude is provisional and unmeasured; dwell timing is still counted in frames |
| Dwell click, recenter, pause, clutch, progress ring | **LIVE (opt-in)** | `headpointer/controller.py`, overlay dwell ring (#405) | accessibility co-design and fatigue study (#419) before any default is recommended |
| Gesture chords from face + head tokens | **LIVE (opt-in)** | `gesture/{chords,headmotion,sensors,engine,runtime}.py`, `[gesture.chords]`, `yazses gesture ...` (#408) | a 'hold' token; confirmation prompt for non-reversible chord actions (they are refused today); real-hardware false-activation evidence |
| Face-gesture switch | **LIVE** | `facegesture/{detector,calibration,levels,switches,backend}.py`, `yazses facegesture calibrate [--active --talk]`, ADR-v2-135, ADR-v2-147 (#406, #407); leases the shared camera when `[perception]` is on | `select`/`confirm`/`cancel` have no daemon entry point; derived thresholds' fractions are starting values; false-activation evidence beyond one person (harness: #409); the stuck-open guard `max_hold_s` is off by default (no data on how long people legitimately hold) |
| Shared camera/perception source | **LIVE (opt-in)** | ADR-v2-145, `perception/`; leased by Glance-Type gaze (#396), the Head-Pointer (#404), the face switch and the chords runtime | all consumers lease it when `[perception]` is on and the camera indexes match; otherwise gaze and the face switch keep their own capture |
| Wayland pointer injection | **LIVE (opt-in), untested on a real compositor** | portal `PointerSink` (#403) on the keyboard injector's own session via a deferred sink | consent flow on real GNOME/KDE; a 'pending' state so the first head movement does not fault before the dialog is answered |
| Dedicated eye tracker backend | **RESEARCH** | eye-control research | provider protocol + licensing/device study |
| Grounded semantic target resolution | **DESIGNED / proposed** | ADR-v2-151 + `eye-grounded-targets.md` | #441–#445; structured semantic source evidence |
| Hands-free controls window + `yazses handsfree` | **LIVE** | `handsfree/{panel,panel_io}.py`, `settingsui/handsfree_panel.py` (#420) | visual / screen-reader verification on a real screen; a spoken-command binding and a tray Pause item |
| False-activation replay harness | **LIVE (offline)** | `eyeeval/switch_replay.py`, `scripts/replay_face_switch_trace.py` (#409) | real volunteer traces; no threshold may be read off the synthetic fixtures |
| Hands-free bundle/profile | **DESIGNED** | #102, #410 | compose features into one usable mode (in progress) |

### Important planning corrections

1. **Issue #101 was closed with only the pure implicit-calibration estimator present.**
   Click capture and the guarded apply/rollback path now exist (#397, #398), but no platform ships a
   click observer yet, so implicit calibration is still dormant everywhere. Do not describe it as
   delivered until an OS backend and a field measurement exist.
2. **`headpointer` and `gesture` already have generic campaign tasks**
   (`WIRE-HEADPOINTER-001`, `WIRE-GESTURE-001`) under #164. New issues should refine those tasks
   and satisfy them, not create a second competing implementation.
3. **The Face-Gesture Switch shipped while this programme was being written, and the
   audit above was rewritten to match.** ADR-v2-135 landed on 2026-09-04 with a pure
   detector, a `HotkeyBackend` capture loop, a `[facegesture]` config section, a registry
   entry and two test files, so it is **LIVE**, not DESIGNED. The earlier revision of this
   document said no detector or activation adapter existed; that claim was already false
   when it was written down, and it was copied onward into the Windows packaging rationale
   before anyone re-ran the search. What remains open for this programme is not building
   the detector but subordinating it. That is now done: it leases the shared source of
   ADR-v2-145 (when `[perception]` is on) and emits the switch intents of ADR-v2-147.
4. **Wayland is less blank than #102 suggests.** Keyboard RemoteDesktop portal code was already
   substantial, and the pointer now extends that same session (a deferred sink, one consent dialog).
   It has not yet met a real compositor's dialog.

## Existing ADRs that remain authoritative

- [ADR-v2-010 — Gaze-Routed Dictation & Point-and-Speak](../adr/adr-v2-010-gaze-routed-dictation.md)
- [ADR-v2-043 — Gesture Chords](../adr/adr-v2-043-gesture-chords.md)
- [ADR-v2-052 — Head-Pointer](../adr/adr-v2-052-head-pointer.md)
- [ADR-011 — privacy / local camera handling](../adr/adr-011.md)
- [ADR-014 — held-out validation](../adr/adr-014-tune-holdout-validation.md)
- [ADR-v2-129 — killer features follow-up list](../adr/adr-v2-129-killer-features-10x.md)
- [ADR-v2-145 — shared camera perception](../adr/adr-v2-145-shared-camera-perception.md)
- [ADR-v2-146 — pointer-output boundary](../adr/adr-v2-146-pointer-output-boundary.md)
- [ADR-v2-147 — face gesture emits switch intent](../adr/adr-v2-147-face-switch-intent.md)
- [ADR-v2-148 — hands-free composition + global safety state](../adr/adr-v2-148-hands-free-composition.md)
- [ADR-v2-149 — calibration coordinate space/topology](../adr/adr-v2-149-gaze-calibration-coordinate-space.md)
- [ADR-v2-151 — ground coarse targets into semantic UI entities](../adr/adr-v2-151-grounded-target-resolution.md)
- [ADR-v2-150 — community QA vs human research evidence](../adr/adr-v2-150-evaluation-evidence-and-research-consent.md)

ADR-v2-145 and the follow-on programme ADRs do **not** replace those
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
- [RESEARCH_PARTICIPANT_TEMPLATE.md](RESEARCH_PARTICIPANT_TEMPLATE.md) — pre-recruitment information/consent template;
- [VALIDATION_MATRIX.md](VALIDATION_MATRIX.md) — same-task cross-OS/computer/person replication matrix;
- [BEGINNER_TESTING.md](BEGINNER_TESTING.md) — pick-one no-code contributor guide;
- [VALIDATION_OPERATIONS.md](VALIDATION_OPERATIONS.md) — slot lifecycle, readiness, A/B replication and contributor-credit rules.
