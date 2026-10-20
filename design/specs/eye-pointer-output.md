# Spec: Pointer Output — Cross-Platform Motion, Click and Scroll Boundary

| Field | Value |
|---|---|
| **ID** | spec-eye-pointer-output |
| **Status** | Proposed |
| **Date** | 2026-09-22 |
| **Modules** | new pointer protocol/backend area; extend existing Wayland portal code |
| **Related** | ADR-v2-146, ADR-v2-052, ADR-v2-030 |
| **Issues** | #400–#403 |

## Goal

Expose one platform boundary for pointer intent so Head-Pointer, voice grid and future gaze-assisted
control do not contain platform commands.

## Non-goals

- no head pose;
- no dwell policy;
- no face switch;
- no target-selection policy;
- no destructive-action confirmation;
- no screen-reading/accessibility tree.

## Contract

Required operations:
- `move_relative(dx, dy)`;
- `click(button)`;
- `scroll(dx, dy)`;
- `capabilities()`;
- `close()`.

Optional:
- `move_absolute(x, y)`.

### Units

Relative movement is expressed in **logical desktop pointer units** as defined by the chosen platform
backend. Feature code treats values as deltas and does not convert DPI itself.

What a unit *is* differs per backend and is declared in `PointerCapabilities.motion_unit`
(`src/yazses/pointer/base.py` holds the table): a framebuffer pixel on X11 (no HiDPI factor),
a logical point on macOS, a mouse count subject to the pointer-speed setting on Windows, and
a compositor-defined logical pixel on the Wayland portal (specification's claim; unverified
on a real scaled session).

Absolute coordinates, when supported, use the canonical desktop coordinate space from ADR-v2-149 /
platform geometry helpers.

The protocol/spec implementation must document conversion at the backend boundary.

### Bounds

A sink does **not** clamp, wrap or re-origin a coordinate. This follows from two rules
already written down rather than adding a new one: ADR-v2-149 requires negative coordinates
for displays left of or above the primary to be reachable "if the OS exposes them", and this
spec's safety boundary keeps the sink deliberately dumb, so it cannot know the topology a
clamp would need. Specifically:

- `move_absolute` passes the position through unchanged, negative and beyond-the-primary
  values included. What lies off every display is the OS's to settle. Choosing a sensible
  target is the caller's job, using the platform geometry helpers.
- `move_relative` is neither capped nor split. Speed limits live in the feature
  (Head-Pointer caps its own velocity), and one call is one effect.
- A value the native field cannot represent (for example a Windows `LONG` overflow) is
  refused with an explicit backend error, never wrapped or truncated.

The shared contract suite asserts the first two against every backend
(`tests/pointer_contract.py`), and `tests/test_pointer_contract_mutants.py` proves it fails a
sink that clamps, caps or splits.

## Capabilities

A structured capability value reports:
- relative motion;
- absolute motion;
- buttons available;
- horizontal/vertical scroll;
- backend identifier.

Unsupported operations raise/return an explicit supported-domain error. They never silently succeed.
That error is the same whatever state the sink is in: an operation the capabilities rule out
stays *unsupported* (permanent) while the backend is failing and after `close()`. It is
never reported as a backend failure (possibly transient) that a caller might retry.

## Buttons

At minimum:
- left;
- right.

Middle/extra buttons are optional and must not be assumed by feature code.

A click is a complete press+release operation unless a future separate hold-button protocol is
explicitly added.

## Error semantics

Backend error:
- stops that requested action;
- does not repeat the last action;
- is surfaced to caller/status;
- does not crash ordinary dictation.

No backend maintains an implicit velocity/motion loop.

## X11 backend

Requirements:
- hidden behind pointer backend class;
- external tool/API invocation injectable/fakeable;
- no command construction in Head-Pointer;
- coordinates/button names validated before external call.

## Wayland portal backend

Extend `src/yazses/inject/portal.py` session.

Requirements:
- one RemoteDesktop session;
- request `POINTER` when needed;
- preserve `KEYBOARD` for existing portal injection;
- restore-token behavior unchanged;
- no events before session permission;
- refusal/unavailable is explicit;
- pointer motion/button/axis D-Bus calls tested with fakes;
- no `/dev/uinput` or privileged helper for portal path;
- keyboard and pointer events share one connection, so sends are serialised one message
  at a time across threads, and the keyboard's messages are byte-identical with or without
  a pointer consumer on the session;
- the pointer grant follows the `SelectDevices` mask that was sent, so a consumer that
  leaves while the dialog is open does not discard a grant for the next one.

Absolute motion stays unsupported on this backend: `NotifyPointerMotionAbsolute` takes a
ScreenCast stream node id, and acquiring a stream would turn a keyboard/pointer grant into
screen capture. Changing that needs a design decision first, not an implementation change.

## macOS backend

Use supported native synthetic pointer API. Imports are platform guarded and fakeable.

Post-event access (System Settings > Privacy & Security > Accessibility) is checked when the
sink is **opened**, by the platform factory `build_macos_pointer_sink`, and again before each
post until it is confirmed. A missing Quartz bridge is `PointerUnsupportedError`. A denial is
`PointerBackendError`, because a grant plus a restart fixes it. Either way the Head-Pointer
gets a status reason at build time, not a failure on the first head movement. The check uses
`CGPreflightPostEventAccess`, which does not prompt.

Camera permission is unrelated to pointer injection and remains separate.

## Windows backend

Use supported mouse event injection behind platform guards. Do not conflate MSIX camera capability
with pointer output.

## Factory

Pointer selection follows existing platform bundle/factory patterns.

The feature can ask for a pointer sink without importing every platform backend.

## Safety boundary

PointerSink is deliberately dumb:
- it does not implement dwell;
- it does not confirm;
- it does not know whether a face gesture is deliberate;
- it does not own the global pause state.

Global pause/safety prevents calls from reaching the sink.

## Acceptance criteria

- Same fake contract suite passes against each backend adapter.
- Relative motion order/values are exact in tests.
- Click produces press then release exactly once.
- Scroll direction is documented/tested.
- Unsupported absolute motion is explicit.
- Backend failure does not replay stale input.
- Wayland portal asks for pointer capability only when needed.
- Existing keyboard portal tests remain green.

## Tests

- `tests/test_pointer_contract.py` or equivalent reusable suite;
- X11 command/API fake;
- macOS native API fake;
- Windows native API fake;
- Wayland portal D-Bus fake;
- portal restore/refusal regression tests.

## Live smoke evidence

Before marking a backend experimentally supported:
- one real motion;
- one click;
- one scroll where supported;
- pause/stop releases control;
- normal dictation remains usable after pointer backend denial/failure.
