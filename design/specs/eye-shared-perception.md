# Spec: Shared Camera Perception — One Webcam, Derived Signals, Multiple Consumers

| Field | Value |
|---|---|
| **ID** | spec-eye-shared-perception |
| **Status** | Proposed |
| **Date** | 2026-09-22 |
| **Modules** | new `src/yazses/perception/`; adapter changes in `src/yazses/gaze/` |
| **Related** | ADR-v2-135, ADR-011, ADR-v2-010 |
| **Issues** | #393–#396 |

## Goal

Create one lazy, privacy-bounded camera/FaceLandmarker source that can serve gaze, head pose and face
switches without multiple consumers opening or processing the webcam independently.

## Non-goals

- no gesture classification;
- no pointer movement;
- no calibration-policy rewrite;
- no dedicated eye tracker;
- no raw-frame event bus;
- no identity/emotion/attention inference.

## Public data contracts

Public perception values are immutable Python dataclasses/protocol values with **derived numbers
only**.

Required semantics:

### Common

- `timestamp_s`: monotonic timestamp of the source observation;
- `confidence` or quality: normalized/documented;
- no cv2/MediaPipe object references;
- no raw bytes/images.

### GazeSignal

Carries raw/calibration-input gaze features, not necessarily final screen coordinates. The existing
gaze adapter remains responsible for calibration semantics.

Suggested fields:
- timestamp;
- normalized iris/eye feature x/y;
- confidence;
- optional head-motion quality if used for gating.

### HeadPoseSignal

- timestamp;
- yaw/pitch/roll in documented units (radians preferred internally);
- confidence.

### FaceSignal

- timestamp;
- normalized `Mapping[str, float]` blendshape scores needed by switch detection;
- confidence/face presence.

The implementation may combine these in `PerceptionSample`.

## Lifecycle

### States

```text
DORMANT
  -> STARTING (first consumer)
  -> RUNNING
  -> DEGRADED (camera/model alive but one channel unavailable)
  -> FAILED (source unavailable; no actions)
  -> STOPPING
  -> DORMANT (last consumer released)
```

A simpler implementation may not materialize an enum, but tests must cover equivalent behavior.

### Consumer ownership

The source tracks consumers by lease/subscription, not by each feature independently owning camera
close.

Rules:
- consumer count 0 -> camera closed;
- first consumer -> open once;
- additional consumer -> no additional open/model instance;
- last release -> close;
- duplicate release/close -> harmless;
- process shutdown -> close regardless of lease bookkeeping.

## MediaPipe configuration

One FaceLandmarker result should request/provide what enabled consumers need:
- landmarks for iris/gaze;
- facial transformation matrix for head pose where available;
- blendshapes for face switches.

Optimization is allowed: if only gaze is enabled, the implementation may disable unused expensive
outputs if MediaPipe permits dynamic/source-level configuration without creating a second camera.

Correctness rules:
- no second capture loop for another consumer;
- channel-specific absence does not kill other channels;
- timestamp alignment comes from the same source observation where possible.

## Threading

The camera/model may run on a worker thread/live callback.

Requirements:
- public latest-sample read is thread-safe;
- shutdown cannot leave capture/model thread alive;
- callback never blocks on desktop action;
- consumer exceptions do not crash source loop;
- the source does not call feature actions.

## Freshness

Each consumer can determine whether a sample is too old.

The source records the true source timestamp. It must not refresh a stale sample timestamp merely
because a consumer read it.

## Lazy dependency contract

When no camera feature is enabled:
- importing core YazSes does not import `cv2` or `mediapipe`;
- no model path is resolved/downloaded;
- no camera probe occurs.

Optional dependencies remain behind the existing gaze/camera feature installation path unless a later
ADR changes packaging.

## Model lifecycle

Reuse the existing FaceLandmarker model asset/download policy.

The source:
- can reuse an already downloaded model;
- reports model-missing/download failure accurately;
- does not trigger hidden network activity merely because `doctor` probes the feature;
- keeps runtime inference offline after asset availability.

## Failure behavior

| Failure | Behavior |
|---|---|
| camera open fails | source unavailable; ordinary dictation continues |
| model missing/download blocked | camera feature unavailable with actionable reason |
| no face | signal None/low quality; no last-value replay |
| head transform missing | gaze/face may continue |
| blendshapes missing | gaze/head may continue |
| worker exception | stop emitting actions, status FAILED, ordinary dictation alive |
| consumer slow | source loop must not wait on consumer action |

## Privacy

Hard requirements:
- raw frames are not persisted;
- raw frames are not sent over IPC;
- raw frames are not logged;
- default measurement export does not include landmarks/blendshapes;
- no runtime network call carries camera-derived data.

## Observability

Expose derived state sufficient for `doctor`/daemon status:
- camera feature requested yes/no;
- source state;
- backend/model name;
- last sample age;
- active consumer names/count if safe;
- failure reason;
- no biometric detail.

## Acceptance criteria

- Given zero consumers, camera/model are not imported/opened.
- Given first consumer, capture opens exactly once.
- Given two consumers, capture/model count remains one.
- Given one consumer release, remaining consumer continues.
- Given final release, camera closes.
- Given no face, no stale sample is replayed as new.
- Given missing head transform, gaze sample still survives.
- Given failed camera, ordinary daemon path remains usable.
- Existing gaze behavior remains unchanged after #396.

## Required tests

- pure signal dataclasses;
- fake capture/model lifecycle;
- multi-consumer one-open test;
- shutdown/idempotence;
- per-channel degradation;
- lazy-import/no-camera test;
- existing `tests/test_gaze_mediapipe.py`;
- existing `tests/test_gaze_wiring.py`.

## Definition of done

```sh
uv run python -m pytest tests/test_gaze_mediapipe.py tests/test_gaze_wiring.py tests/ -q
uv run ruff check .
uv run mypy src/yazses
```

Live-camera measurement is required before feature-tier promotion, not to merge the pure/source
foundation.
