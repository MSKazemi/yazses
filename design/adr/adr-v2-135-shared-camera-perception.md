# ADR-v2-135 — Shared camera perception source for gaze, head pose and face switches

**Status:** Proposed (2026-09-22)  
**Context links:** [[adr-v2-010-gaze-routed-dictation]], [[adr-v2-043-gesture-chords]], [[adr-v2-052-head-pointer]], [[adr-011]]

## Context

YazSes now has three camera-shaped accessibility capabilities at different maturity levels:

1. **Glance-Type / gaze routing** is live. `gaze/mediapipe_backend.py` owns an OpenCV webcam and a
   MediaPipe FaceLandmarker, derives iris offsets and returns a gaze estimate.
2. **Head-Pointer** has a tested pure `pose_to_cursor` + `DwellClicker` core but no runtime camera
   source or pointer sink.
3. **Face-gesture switches** are planned in #102 but do not have a runtime detector.

All three can be derived from the same MediaPipe FaceLandmarker result. Current MediaPipe APIs can
return face landmarks, blendshapes and facial transformation matrices from one live-stream model
instance.

If each feature opens its own `cv2.VideoCapture` and creates its own landmarker, YazSes gets:

- camera contention ("device already busy");
- duplicated CPU/model work;
- inconsistent frame timing;
- separate confidence/failure behavior;
- multiple places that could accidentally violate the frame-in-RAM privacy rule;
- a daemon whose behavior depends on which camera feature happened to initialize first.

The repository already contains troubleshooting for the daemon holding the webcam during gaze
calibration. Adding more independent camera owners would make that class of failure structural.

## Decision

Introduce one **shared, lazy camera perception source** inside the daemon.

The source owns the physical camera and FaceLandmarker lifecycle. It emits **derived, immutable,
timestamped signals**, not frames:

- gaze/iris signal + quality;
- head pose signal + quality;
- face blendshape signal + quality/presence.

Feature adapters consume only the signal family they need.

### Invariants

1. **One physical camera owner per daemon.**
2. **Zero camera work when no camera feature is enabled.**
3. **Frames stay inside the source and are never part of the public event contract.**
4. **No MediaPipe/OpenCV types cross the source boundary.**
5. **Consumers can be tested with numeric fakes and no optional camera dependencies.**
6. **Failure of one derived channel does not necessarily kill the others.** Missing transformation
   matrix can disable head pose while gaze landmarks remain usable.
7. **Confidence is explicit.** No consumer interprets missing/low-quality data as `0,0`.
8. **Lifecycle is reference/subscriber driven.** First active consumer starts; final consumer closes.
9. **Always-on camera behavior requires explicit feature enable.** Gaze used only at hold time can
   remain burst-oriented; head pointer/face switch may need a continuous source while enabled, and
   UI/status must make that state observable.
10. **No identity/emotion inference.** Blendshapes are treated only as control features.

## Conceptual interfaces

Names are non-binding; the separation is binding.

```python
class FacePerceptionSource(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def latest(self) -> PerceptionSample | None: ...

@dataclass(frozen=True)
class PerceptionSample:
    timestamp_s: float
    gaze: GazeSignal | None
    head_pose: HeadPoseSignal | None
    face: FaceSignal | None
```

A callback/subscription API is acceptable if it keeps the same ownership and privacy properties.

### Gaze compatibility

Existing `GazeTargeter` should receive a small gaze-provider adapter so the routing/deixis logic
does not care whether samples came from:

- shared webcam perception;
- current L2CS optional backend;
- a future dedicated eye tracker.

The ADR does not require deleting L2CS. It requires that each **physical camera** has one owner in the
active runtime path.

### Camera vs dedicated tracker

A dedicated eye tracker is not a camera-perception consumer. A future `GazeSampleProvider` can
bypass the webcam source and feed the same calibration/route/safety layer.

## Alternatives considered

### A. Keep one camera per feature

Rejected. Easiest for a single PR; worst system behavior once two features are enabled.

### B. Let Head-Pointer reuse the existing gaze backend object directly

Rejected. It couples head control to a gaze-specific API and makes face switches depend on a class
whose public meaning is "estimate gaze".

### C. Run three independent MediaPipe task instances over copies of each frame

Rejected for the default path. It keeps camera ownership centralized but duplicates inference and
can desynchronize signals that are supposed to describe the same face at the same time.

A specialized backend may run extra inference later if measured quality demands it, but the common
FaceLandmarker result is the first implementation.

### D. Put raw landmarks on a global event bus

Rejected. It leaks model-specific detail through the architecture, makes privacy review harder, and
encourages every consumer to re-derive slightly different head/gesture semantics.

## Consequences

### Positive

- gaze + head + face features can coexist;
- camera lifetime and privacy are auditable in one place;
- one inference yields multiple useful signals;
- agent-sized consumers remain dependency-free;
- hardware failures become a shared diagnostic instead of feature-specific mystery;
- future alternate gaze hardware plugs above the same route/safety layer.

### Costs

- live gaze code must be refactored without regression;
- continuous head/face control changes camera duty cycle relative to burst-only gaze;
- source lifecycle and thread safety need dedicated tests;
- MediaPipe options may increase per-frame computation when blendshapes/transforms are requested, so
  CPU/FPS must be measured rather than assumed.

## Validation

Before this ADR can move from Proposed to Accepted, the implementation plan/PR should show:

- all current gaze tests green;
- a fake source feeding at least two consumers;
- an assertion that the camera is opened once;
- close/restart behavior;
- a privacy test or code inspection proving frames do not enter persistence/log/export paths;
- measured CPU/FPS from at least one ordinary laptop, recorded as environment-specific evidence,
  not a universal claim.

## Delivery

See `design/eye-control/ROADMAP.md` Phase 1 and tasks EYE-ARCH-001 through EYE-CAM-003.
