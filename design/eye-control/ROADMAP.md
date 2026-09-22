# Eye / camera control roadmap

**Programme:** [README](README.md)  
**Milestone:** `Hands-free — perception & accessibility` (#10)  
**Parent epic:** [#102](https://github.com/MSKazemi/yazses/issues/102)

This roadmap is dependency-ordered. A task may be implemented by an inexperienced contributor or a
coding agent **only after its prerequisites are merged**. No task requires understanding the whole
daemon.

## Architecture target

```text
                         +-----------------------+
camera ---------------->| Shared FacePerception |
                         | one owner / one model |
                         +-----------+-----------+
                                     |
             +-----------------------+------------------------+
             |                       |                        |
        GazeSample               HeadPose                FaceSwitch
             |                       |                        |
       calibration             pose_to_cursor          gesture detector
             |                       |                        |
       GazeTargeter             PointerSink             ActivationSource
             |                       |                        |
   route/deixis context       move/click/scroll      hold/click/confirm
             +-----------------------+------------------------+
                                     |
                              safety / feedback
                                     |
                                YazSes daemon

Dedicated eye tracker (future) ---> GazeSampleProvider ---> same calibration/target/safety path
```

The camera source owns frames and model inference. Consumers receive **derived signals only**. This
keeps privacy boundaries obvious, prevents webcam contention, and makes every consumer testable with
numeric fake samples.

## Phase 0 — make the planning truth explicit

**Outcome:** contributors stop rediscovering what is implemented.

- [x] Audit gaze, headpointer, gesture, Wayland portal, tests, ADRs and research.
- [x] Define LIVE / CORE / DESIGNED / RESEARCH status vocabulary.
- [x] Add this programme record.
- [ ] Correct stale packaging/docs claims that Face-Gesture is already implemented.
- [ ] Link child issues from #102 and #377.

**Exit gate:** the status table in `README.md` agrees with code and `docs/features.md`.

## Phase 1 — shared camera/perception foundation

**Why first:** today the gaze backend owns the webcam. Head pointer and face switches need the same
FaceLandmarker. Opening separate `cv2.VideoCapture` objects is fragile and wastes CPU.

### P1.1 — signal contracts

Define small immutable values, e.g.:

```python
@dataclass(frozen=True)
class GazeSignal:
    timestamp_s: float
    raw_x: float
    raw_y: float
    confidence: float

@dataclass(frozen=True)
class HeadPoseSignal:
    timestamp_s: float
    yaw: float
    pitch: float
    roll: float
    confidence: float

@dataclass(frozen=True)
class FaceSignal:
    timestamp_s: float
    blendshapes: Mapping[str, float]
    confidence: float
```

The exact names are implementation choices; the invariants are not:

- no OpenCV/MediaPipe objects in public signal types;
- no raw image bytes;
- monotonic timestamp;
- confidence is explicit;
- missing signal is representable without fake zeros.

### P1.2 — single-owner lifecycle

Introduce a `FacePerceptionSource` (name may change) that owns:

- camera open/close;
- FaceLandmarker instance;
- optional live-stream thread;
- latest derived sample;
- subscriber lifecycle;
- clean shutdown.

It must be dormant when no camera capability is enabled.

### P1.3 — one MediaPipe result, multiple adapters

Configure Face Landmarker so the same result can provide:

- 478 landmarks / iris offsets for existing gaze;
- transformation matrix or derived pose for head pointer;
- blendshapes for face switches.

Refactor existing gaze onto an adapter without changing user-visible Glance-Type behaviour.

**Phase 1 exit gates**

- enabling gaze still passes all existing gaze tests;
- a fake source can feed gaze/head/face consumers with no camera dependencies installed;
- enabling two camera consumers opens the camera once;
- disabling all consumers closes it;
- no frame persistence/network path is added;
- `yazses doctor`/status can explain camera-source failure without logging frame data.

## Phase 2 — finish gaze work that is currently half-delivered

### P2.1 — implicit click capture

`gaze/implicit.py` already contains the estimator and held-out comparison. Add the missing runtime
sample collection:

- opt-in only;
- pair a desktop click with a nearby timestamped gaze sample;
- reject low-confidence samples;
- do not retain raw frames;
- isolate platform click observation behind a protocol so CI can fake it.

### P2.2 — safe apply / persistence

Wire the candidate map through `refined_if_better` and existing calibration persistence.

Rules:

- the existing explicit calibration is the baseline;
- candidate applies only after the held-out gate wins;
- rollback is possible;
- status tells the user whether the active map is explicit or implicitly refined;
- a failed/refused refinement leaves the baseline unchanged.

### P2.3 — measurement command

Turn issue #104 from free-form anecdotes into comparable evidence. Add an opt-in command that emits a
small local JSON/Markdown report containing **derived metrics only**, for example:

- camera/backend identifiers the user chooses to report;
- calibration point error in px and, when geometry is supplied, degrees;
- confidence distribution;
- routing attempts / wrong-target corrections;
- drift over session time;
- glasses/lighting/screen-distance fields supplied by the tester.

No frames, face landmarks, screenshots, or typed text belong in the report.

**Phase 2 exit gate:** #104 can collect reproducible measurements and implicit calibration can never
replace a better baseline in tests.

## Phase 3 — pointer-output substrate

Head pointer cannot ship by directly shelling out from its feature module. Define one pointer-action
boundary first.

### P3.1 — `PointerSink` protocol

Operations:

- relative motion;
- optional absolute motion;
- left/right click;
- scroll;
- capability query;
- clean failure.

A fake sink must make head-pointer tests fully hermetic.

### P3.2 — desktop backends

Implement in small independent changes:

1. X11/Linux backend using the project's existing desktop/injection conventions.
2. macOS and Windows backends using the existing platform abstraction.
3. Wayland RemoteDesktop portal extension:
   - request POINTER alongside/when needed in the existing session;
   - relative/absolute motion;
   - button events;
   - preserve current keyboard-injection behaviour and restore-token handling.

Wayland support must not invent a second consent/session implementation.

**Phase 3 exit gate:** the same pure pointer contract passes on fake, X11, macOS/Windows tests and
portal protocol fakes.

## Phase 4 — make Head-Pointer real

The existing `pose_to_cursor` and `DwellClicker` cores stay authoritative.

### P4.1 — head-pose adapter

Convert shared perception output into yaw/pitch/roll plus quality. Add a neutral centre calibration
and a re-centre command.

### P4.2 — runtime loop

Wire:

```
HeadPoseSignal -> pose_to_cursor -> PointerSink.move_relative
                            \
                             -> DwellClicker -> PointerSink.click
```

Reference the existing campaign task `WIRE-HEADPOINTER-001`; completing this phase should satisfy,
not duplicate, that wiring item.

### P4.3 — clutch, pause and feedback

A continuous pointer needs an escape hatch:

- pause/resume command;
- optional face/speech/keyboard clutch;
- visible dwell progress before a click;
- dwell can be disabled independently;
- pointer must not click on startup or after signal loss;
- signal loss freezes motion rather than repeating the last delta.

**Phase 4 exit gate:** a user can operate pointer + click without a hand on at least one desktop
backend, and the fake trace tests prove no phantom click on jitter/signal loss.

## Phase 5 — deliberate face-gesture switches

### P5.1 — pure detector

Build a detector over numeric blendshape traces, not webcam frames.

Initial candidate gestures:

- open mouth;
- raise eyebrows;
- smile (optional);
- blink (advanced/opt-in only).

Detector requirements:

- short neutral calibration or baseline normalization;
- separate enter/exit thresholds (hysteresis);
- minimum hold duration;
- refractory/debounce interval;
- confidence gate;
- exactly one event per deliberate gesture.

### P5.2 — switch adapter

Convert detector events to an abstract activation/switch token. Do **not** let detector code call
mouse/daemon actions directly.

Allow user mapping such as:

```toml
[face_switch]
enabled = false
primary = "mouth_open"
primary_action = "hold_to_talk"
secondary = "brow_raise"
secondary_action = "confirm"
```

Names/defaults are subject to implementation review. All mappings remain opt-in.

### P5.3 — Gesture Chord integration

Feed face/head tokens into the existing `gesture/chords.py` resolver. Reference
`WIRE-GESTURE-001`.

Important: when a commit expression materially disturbs head pose, pointer motion may be frozen for
the gesture interval, following the failure mode observed in Project Gameface.

### P5.4 — false-activation study

Before recommending defaults, measure events/hour from numeric traces and real volunteer sessions.
The shipping question is not only classifier accuracy; it is **phantom actions over a workday**.

**Phase 5 exit gate:** no facial switch becomes "recommended" until false-activation evidence exists.
Experimental/off remains acceptable before that.

## Phase 6 — compose a usable hands-free mode

Individual controls are not the product. Add a `handsfree` preset/bundle that composes already
independently testable capabilities:

- speech for text;
- gaze for target/context;
- head pose for pointer;
- face switch/dwell/EMG/voice for commit;
- confirmation policy for destructive actions;
- read-back/notification for feedback;
- voice mouse grid as precision/fallback option.

The bundle config must expand to ordinary feature configs rather than creating a second daemon path.

### Recovery hierarchy

1. high-confidence preferred signal;
2. lower-risk alternate modality;
3. focused/current target;
4. explicit "cannot act" feedback.

Never silently switch from a failed gaze route to a destructive action on another window.

## Phase 7 — dedicated eye tracker seam (after webcam programme is stable)

First create an implementation-neutral `GazeSampleProvider` contract and a device capability study.
Only then consider vendor backends.

Research checklist:

- SDK/API availability on Linux/macOS/Windows;
- redistribution/runtime licensing;
- calibration ownership;
- device discovery;
- sample rate and timestamp semantics;
- normalized vs screen coordinates;
- commercial/non-commercial restrictions;
- whether a generic OS eye-tracking API exists on each platform.

A dedicated tracker may unlock precision pointer experiments, but must not change the webcam
accuracy claims.

## Dependency graph

```text
P1 shared perception
  +--> P2 implicit gaze + measurement
  +--> P4 head pointer --------+
  +--> P5 face switches -------+--> P6 hands-free bundle
P3 pointer sinks --------------+
                                 +--> P7 dedicated tracker (independent gaze provider)
```

## Delivery policy for small PRs

A child issue should normally change one seam or one backend. Good shapes:

- protocol + tests;
- one adapter + tests;
- one platform sink + tests;
- one detector + synthetic traces;
- one wiring path + reachability test;
- one documentation/measurement task.

Bad shapes:

- "implement eye control";
- "finish hands-free";
- camera + pointer + gestures + UI in one PR;
- a feature that can only be tested with the contributor's webcam.

Every implementation issue must name its allowed files, dependencies, unit tests, and hardware
evidence separately. See [AGENT_TASKS.md](AGENT_TASKS.md).
