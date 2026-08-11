# 03 · Glance-Type — look at a pane to target dictation

> Implementation plan. Spec: `design/specs/glance-type.md`. Roadmap: `ROADMAP.md` §3.3.
> **Build tier C** — re-scoped to coarse "look-to-pane"; the plumbing is the most
> code-buildable of the four (L2CS-Net is pip-installable; user has a webcam).

## Goal
Let the user **glance at a screen region/window** to choose where the next dictation
lands, instead of clicking first. Off by default; needs a webcam + a short calibration.

## Why coarse only
Webcam gaze is **~3–5 cm / ~3.2° still-head**, degrading to ~5°/80 mm with head motion
[dossier; PMC11019238] — fine for "which pane", **not** "which character". So the feature
is **look-to-pane** (coarse zones), with look-to-caret pre-registered as out of scope
until webcam gaze hits <1 cm.

## SoA (2026, verified)
L2CS-Net is **pip-installable** (`Ahmednull/L2CS-Net`, pretrained ResNet, `Pipeline`
over `cv2.VideoCapture`, yaw/pitch out); MediaPipe FaceMesh/Iris for landmarks; both
mature [web:github Ahmednull/L2CS-Net]. This is the most "off-the-shelf" of the four.

## Module layout
```
src/yazses/gaze/
  __init__.py
  base.py        # GazeBackend Protocol (estimate() -> (yaw, pitch) | None) + Null
  l2cs.py        # L2csGazeBackend (l2cs-net + opencv; optional `gaze` extra)
  factory.py     # build_gaze(cfg) -> backend | None (dormant/Null contract)
  calibrate.py   # map gaze angle -> screen zone (N-point calibration, pure math)
  zones.py       # screen → zones (grid or per-window); zone → target window
```
Reuses: the platform window detector (route the injection to the window under the gaze
zone), the recorder hold lifecycle (sample gaze on hold-start).

## Config (`[gaze]`, off by default)
```toml
[gaze]
enabled = false
backend = "l2cs"               # l2cs | none
zones = "windows"              # windows | grid3x3 | grid2x2
camera_index = 0
calibration_points = 9         # collected once, stored locally
sample_on = "hold_start"       # sample gaze when the hotkey is pressed
confidence_min = 0.5
```

## P1 — look-to-pane (plumbing buildable now; gaze needs the webcam)
1. **Calibration** (`calibrate.py`, pure math): collect (gaze angle → known screen
   point) pairs at N points; fit a 2D mapping (affine/polynomial). Store locally
   (not biometric — but frames are never stored; ADR-011).
2. **Zone mapping** (`zones.py`): map a calibrated gaze point to a coarse zone
   (3×3 grid, or the bounding boxes of the current top-level windows from the window
   detector). `zone_to_window(zone) -> window`.
3. **Wire** into `_on_hold_start`: if `[gaze] enabled`, sample one gaze estimate, resolve
   the zone → target window, and route the dictation injection to that window (the
   injector already targets the focused window; here we pre-focus/route the target).
4. **Camera discipline:** the backend opens the camera only during a hold, reads one
   frame, never stores or transmits it (ADR-011). `yazses doctor` reports the `gaze`
   extra + camera availability.
**TDD (in-env):** calibration fit on synthetic point pairs; gaze→zone mapping (grid +
window-bbox); zone→window routing with fake windows; dormant/Null + no-webcam path; a
fake gaze backend drives the daemon hold path. **Needs hardware:** the webcam for real
gaze accuracy (the LOFA: ≥80% correct zone selection at the user's desk).

## CLI / IPC
- `yazses gaze calibrate` — run the N-point calibration wizard.
- `yazses gaze test` — show the live zone the user is looking at (debug).

## Privacy
Camera active **only during a hold**; frames processed in-RAM and discarded; nothing
stored or sent. Off by default. `doctor` surfaces that the camera is used when enabled.

## Verification map
- **In-env (CI):** calibration math, gaze→zone→window routing, daemon hold wiring (mocked gaze).
- **User machine (has a webcam):** real zone-selection accuracy — the ship gate.
- **Out of scope:** look-to-caret (sensor can't; pre-registered bound).
