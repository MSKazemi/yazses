# ADR-v2-052 — Head-Pointer

**Status:** Accepted (2026-07-02) · Wave G
**Context links:** [[adr-v2-030-mouse-grid]] (discrete vs continuous), [[adr-v2-006-gaze-routing]] (routes text vs moves cursor), [[adr-011]]

## Context

Wave G research (#8) — move and click the mouse by tilting your head, paired with voice for a
fully hands-free desktop. For users with limited hand/arm mobility (RSI, ALS, spinal injury,
tremor) who can speak: head pose drives a continuous pointer, dwell fires clicks, voice handles
text. Completes YazSes's accessibility story from "type by voice" to "operate the machine
hands-free". Anchors: MediaPipe Face Landmarker (3D head-pose matrix + 52 blendshapes incl.
blink, real-time on CPU/webcam).

Distinct from Voice Mouse Grid (selects *discrete* targets by spoken labels) and Gaze-Routing
(routes *dictation destination*) — this is *continuous analog pointer control* by head pose.

## Decision

Add an opt-in **Head-Pointer**: `[headpointer] enabled=false`. Two pure cores: `pose_to_cursor(
yaw, pitch, calib)` maps head angles (with a deadzone) to a cursor delta, and `DwellClicker` — a
state machine that fires a click when the pointer stays within a radius for N frames. Both are
pure math, unit-testable without a camera. The MediaPipe FaceLandmarker capture is deferred
behind a `headpointer` extra. OFF by default.

## Consequences

- Completes the hands-free bundle (voice + wake-word + auto-stop + head pointer).
- Pure mapping + dwell state machine → fully testable with no webcam.
- Privacy (ADR-011): frames processed locally in-RAM; only cursor deltas produced, never stored.
- Caveat: pose jitter/false clicks → deadzone + dwell radius/hold tuning; off by default.
