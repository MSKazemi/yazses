# ADR-v2-149 — Gaze calibration is bound to display topology and camera geometry

**Status:** Proposed (2026-09-22)  
**Context links:** [[adr-v2-010-gaze-routed-dictation]], [[adr-v2-145-shared-camera-perception]], [[adr-014-tune-holdout-validation]]

## Context

A gaze calibration maps camera-derived eye features to desktop coordinates.

That mapping can become wrong without the calibration file changing:

- monitor added/removed;
- resolution or scale changed;
- display arrangement changed;
- laptop lid angle/camera geometry changed;
- external webcam selected;
- camera resolution/crop changed;
- user moves between docked/undocked configurations.

A stale calibration is especially dangerous because it still returns plausible coordinates. The
system may confidently route to the wrong window instead of reporting "uncalibrated".

Multi-monitor and HiDPI also create several coordinate spaces: camera feature space, physical pixels,
logical desktop coordinates and per-monitor scale.

## Decision

Persisted gaze calibration carries an explicit **calibration context/fingerprint** and maps into one
documented canonical desktop coordinate space.

A calibration must not be applied blindly when its context materially differs from the current
environment.

## Context fields

At minimum, persist enough non-sensitive metadata to decide whether the map is still applicable:

- selected camera identifier/index;
- capture resolution/aspect ratio if it affects features;
- display count;
- display rectangles in canonical coordinates;
- per-display scale where relevant;
- primary display / arrangement;
- calibration model/version.

Where camera pose/lid angle cannot be measured reliably, session validation/implicit refinement may
detect drift rather than pretending the context is known.

Do not persist raw frames/landmarks for this purpose.

## Canonical coordinates

The implementation spec must choose and name one canonical coordinate system for calibration and
routing, then centralize conversion at platform boundaries.

Requirements:
- negative coordinates for left/above monitors are supported if the OS exposes them;
- HiDPI logical-vs-physical conversion is explicit;
- window geometry and gaze coordinates are compared only after conversion into the same space;
- tests cover non-1.0 scale and multi-monitor arrangements.

## Validation policy

On startup/use:

1. load calibration and stored context;
2. compare with current context;
3. if exactly/acceptably compatible, use it;
4. if materially changed, mark calibration stale and fall back safely;
5. offer/recommend recalibration or held-out revalidation;
6. never silently rewrite the baseline from a single uncertain sample.

Implicit calibration follows ADR-014-style held-out improvement rules and may refine only a valid
baseline/context.

## Topology changes during a session

If display topology changes while a camera control is active:

- stop gaze routing until geometry is refreshed;
- do not use cached window rectangles from the old topology;
- Head-Pointer relative motion may continue if its own coordinate assumptions remain valid;
- explicit feedback/status should name the reason.

## Alternatives considered

### Store only affine coefficients

Rejected. There is no way to distinguish a good map from one calibrated against a different desktop.

### Auto-scale coefficients to any new resolution/topology

Rejected as a general rule. Some simple scale changes may be transformable, but monitor arrangements
and camera changes are not equivalent. Revalidation is safer.

### Calibrate separately per application window

Rejected. Calibration belongs to sensor->desktop mapping; applications/windows are transient targets.

## Consequences

Positive:
- multi-monitor/HiDPI errors become testable;
- stale calibration fails visibly;
- dock/undock behavior is deterministic;
- field reports can identify calibration context without face data.

Costs:
- calibration persistence schema versioning;
- display topology query per platform;
- users may need revalidation/recalibration after hardware/layout change.

## Implementation

See:
- `design/specs/eye-implicit-calibration.md`;
- multi-monitor/topology child issue;
- #397–#399.
