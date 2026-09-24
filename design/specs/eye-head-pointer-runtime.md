# Spec: Head-Pointer Runtime — Pose to Pointer with Recenter, Clutch and Dwell

| Field | Value |
|---|---|
| **ID** | spec-eye-head-pointer-runtime |
| **Status** | Proposed |
| **Date** | 2026-09-22 |
| **Module** | `src/yazses/headpointer/` + daemon wiring |
| **Related** | ADR-v2-052, ADR-v2-145, ADR-v2-146, ADR-v2-148 |
| **Issues** | #404–#405 |

## Goal

Make the existing pure `pose_to_cursor` and `DwellClicker` cores a safe, reachable, platform-neutral
Head-Pointer feature.

## Non-goals

- do not replace pure pointer math;
- do not add platform mouse calls inside `headpointer`;
- do not use gaze as continuous mouse;
- do not make dwell mandatory;
- do not choose recommended defaults without hardware evidence.

## Pipeline

```text
HeadPoseSignal
 -> freshness/quality gate
 -> neutral/recenter transform
 -> pose_to_cursor()
 -> smoothing/deadzone policy
 -> global ACTIVE/PAUSED/FAULTED gate
 -> PointerSink.move_relative()

pointer position observation
 -> DwellClicker
 -> progress feedback
 -> global gate
 -> PointerSink.click()
```

## Neutral / recenter

Head-Pointer maps deviation from a neutral pose, not absolute anatomical pose.

Recenter:
- captures current valid pose as neutral;
- emits no motion/click during capture;
- resets dwell candidate;
- can be invoked without precise pointer use.

## Freshness

A HeadPoseSignal older than the configured freshness threshold produces **zero motion**.

After tracking loss, a recovered signal must re-enter cleanly; the last delta is never replayed.

## Pause/clutch

Feature-level pause suppresses:
- pointer motion;
- dwell accumulation;
- clicks.

A temporary clutch may freeze motion while held/active without disabling the feature.

Global hands-free PAUSED/FAULTED state also suppresses actions.

## Dwell

Dwell is independently configurable.

Required behavior:
- visible/observable progress before firing;
- movement beyond radius resets;
- pause/reset/signal loss resets;
- one click then re-arm;
- no immediate click on startup/reconnect/recenter.

## Face-gesture interaction

When the configured face commit gesture is active, the composition layer may clutch Head-Pointer so
performing the expression does not move the pointer.

Head-Pointer itself consumes only a generic clutch state, not blendshapes.

## Config

Use existing `[headpointer]` keys where already defined; extend minimally.

Likely keys:
- enabled;
- x/y gain;
- deadzone;
- dwell enabled;
- dwell radius/time or frames;
- freshness timeout;
- optional smoothing;
- recenter action mapping.

All defaults remain off/experimental until field evidence exists.

## Observability

Status should expose:
- enabled;
- paused;
- tracking valid/invalid;
- sample age;
- dwell enabled/progress state without coordinates if unnecessary;
- pointer backend available/name;
- failure reason.

## Acceptance criteria

- Signal inside deadzone -> no move.
- Stale/missing signal -> no move.
- Pause -> no move and no dwell click.
- Recenter -> current pose becomes zero without action.
- Dwell disabled -> never clicks.
- Dwell enabled -> exactly one click after stable dwell, then re-arm.
- Signal loss resets dwell.
- Pointer backend failure faults/suppresses Head-Pointer without crashing dictation.
- Feature registry becomes wired only after a reachable daemon/control path exists.

## Tests

- existing `tests/test_screengrounded_headpointer.py`;
- fake HeadPoseSignal traces;
- fake PointerSink;
- fake clock;
- pause/recenter/recovery;
- feature-wiring honesty tests;
- global safety state tests.

## Hardware gate

Experimental support requires at least:
- target acquisition on large UI targets;
- accidental clicks/hour;
- tracking-loss recovery;
- pause/recenter from a real webcam;
- observation of whether normal speech disturbs head pose.

Recommendation requires multi-person/environment evidence and fatigue review.
