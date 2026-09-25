# Spec: Face-Gesture Switch — Calibrated Deliberate Expression as an Accessibility Input

| Field | Value |
|---|---|
| **ID** | spec-eye-face-switch |
| **Status** | Proposed |
| **Date** | 2026-09-22 |
| **Modules** | `yazses.facegesture` (detector shipped by ADR-v2-135); switch-intent adapter and shared-perception consumer are new |
| **Related** | ADR-v2-147, ADR-v2-043, ADR-v2-145, ADR-v2-148 |
| **Issues** | #406–#409 |

## Goal

Turn selected deliberate facial expressions into robust abstract switch events without letting the
detector execute actions directly.

**What already exists.** `yazses.facegesture.detector.GestureSwitch` is a shipped, tested, pure
hold detector with hysteresis and frame debounce over five named gestures, and
`yazses.facegesture.backend.FaceGestureBackend` drives it from its own webcam. This spec does not
re-specify that detector. It adds the two things ADR-v2-135 deliberately left out: a neutral
per-user baseline instead of absolute thresholds, and a switch-intent boundary so the gesture is not
hard-wired to hold-to-talk. Everything below that describes a detector is a *change to* the shipped
one, not a new module.

## Non-goals

- no identity recognition;
- no emotion inference;
- no medical assessment;
- no raw-image storage;
- no default blink-to-click;
- no recommended threshold before field measurement.

## Input

A timestamped `FaceSignal` from shared perception containing selected blendshape scores and quality.

Detector tests consume numeric traces directly.

## Calibration

Before active detection, collect a short neutral baseline.

Calibration output may include:
- neutral mean/median per required blendshape;
- robust variation estimate;
- derived threshold offsets.

Do not store raw frames. Persist only derived calibration values when persistence is useful.

Calibration must be repeatable/resettable.

## Gestures

Initial supported candidates:
- mouth open;
- eyebrow raise;
- optional smile;
- blink advanced/opt-in only.

Each configured gesture declares the blendshape combination it uses.

Avoid depending on one vendor-specific label outside the adapter; normalize names if needed.

## State machine

Per gesture:

```text
NEUTRAL
 -> CANDIDATE (enter threshold crossed)
 -> ACTIVE (held for minimum duration)
 -> FIRED / HELD
 -> WAIT_FOR_RELEASE (must cross exit threshold)
 -> REFRACTORY
 -> NEUTRAL
```

The implementation may collapse states but tests must establish equivalent semantics.

## Hysteresis

`enter_threshold` and `exit_threshold` differ to prevent chattering.

Threshold interpretation is relative to the calibrated baseline wherever possible.

## Time rules

Configurable:
- minimum hold time;
- refractory/debounce interval;
- sample freshness timeout.

All timing uses monotonic source time/fake clock semantics.

## Event contract

Detector emits a normalized event such as:
- kind;
- phase/fired;
- timestamp;
- confidence.

It contains no PointerSink/action reference.

## Mapping layer

Separate adapter maps event -> abstract action/token:
- hold-to-talk;
- select/click;
- confirm;
- cancel;
- pause/resume;
- Gesture Chord token.

Unknown/unmapped events do nothing.

Destructive desktop operations still use the existing consequence/confirmation policy.

## Talking interference

Mouth-open is explicitly tested against traces resembling normal speaking motion.

Until real false-activation evidence is available:
- mouth-open mapping remains experimental;
- no claim that it is safe while dictating;
- users can choose eyebrow or other deliberate gesture if measured better.

## Blink policy

Natural blink frequency makes blink a poor default commit signal.

Blink:
- never ships as default click;
- may exist as an advanced mapping;
- needs its own false-activation evidence.

## Head-Pointer coupling

The composition layer can assert a clutch while an ACTIVE commit gesture is underway. This prevents
the expression/head movement from shifting the target simultaneously.

## Config

A dedicated optional section may include:
- enabled;
- primary/secondary gesture;
- action mapping;
- per-gesture hold/refractory/threshold adjustments;
- calibration values/path/version;
- confidence minimum.

Config validation rejects unknown gestures/actions and unsafe malformed thresholds.

## Acceptance criteria

- Neutral calibration emits no event.
- Brief threshold crossing shorter than minimum hold emits no event.
- Sustained deliberate trace emits one event.
- Detector must release before re-arm.
- Refractory prevents bounce.
- Low-confidence/stale samples emit no event.
- Ordinary blink trace does not fire a non-blink gesture.
- Talking-like mouth trace is included in regression fixtures.
- Detector never imports daemon/pointer modules.
- Unmapped event causes no action.

## Measurement

Primary field metric:
**false activations per hour** by configured gesture.

Also collect:
- deliberate attempts;
- detected attempts;
- misses;
- latency;
- environment notes.

Synthetic traces are regression tools, not evidence for recommended defaults.
