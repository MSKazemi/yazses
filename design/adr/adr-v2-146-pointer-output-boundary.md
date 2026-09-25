# ADR-v2-146 — Pointer output is a platform boundary, not a Head-Pointer implementation detail

**Status:** Proposed (2026-09-22)  
**Context links:** [[adr-v2-052-head-pointer]], [[adr-v2-030-voice-mouse-grid]], [[adr-v2-145-shared-camera-perception]]

## Context

YazSes has multiple ways to decide **where a pointer should go**:

- Head-Pointer: continuous yaw/pitch -> relative motion;
- Voice Mouse Grid: discrete voice-selected targets;
- future gaze-assisted pointer warping;
- switch/dwell actions that need a click;
- tests/simulators that need to observe pointer intent without moving a real mouse.

The existing injector abstraction types text and key sequences. Pointer motion is a different platform
capability with different permissions and coordinate semantics. If Head-Pointer shells out directly
to `xdotool`, a future Wayland implementation must either special-case Head-Pointer or create a
second abstraction. The same problem then repeats for mouse grid and gaze-assisted control.

Wayland also already has substantial XDG RemoteDesktop session code in
`src/yazses/inject/portal.py`. A separate pointer-only portal client would duplicate consent,
restore tokens, lifecycle and D-Bus failure handling.

## Decision

Create one small **PointerSink** platform boundary.

Conceptual contract:

```python
class PointerSink(Protocol):
    def capabilities(self) -> PointerCapabilities: ...
    def move_relative(self, dx: float, dy: float) -> None: ...
    def move_absolute(self, x: float, y: float) -> None: ...
    def click(self, button: PointerButton = PointerButton.LEFT) -> None: ...
    def scroll(self, dx: float, dy: float) -> None: ...
    def close(self) -> None: ...
```

Exact names may change; these rules may not:

1. The feature producing pointer intent does **not** know the OS backend.
2. Unsupported operations are explicit in `capabilities()`; they are not silent no-ops.
3. Coordinate units/space are documented by the protocol/spec.
4. A stale command is never repeated after backend failure.
5. All implementations can be exercised against a reusable fake/contract suite.
6. Wayland extends the existing RemoteDesktop portal session rather than creating a parallel session.
7. Pointer permission is requested only when a pointer consumer is enabled.
8. The protocol contains no camera, gaze, head-pose or gesture concepts.

## Platform mapping

### Linux / X11

Use an existing YazSes-compatible host mechanism and keep command construction/test fakes behind the
backend. The feature layer must not call `xdotool` directly.

### Linux / Wayland

Extend the existing XDG RemoteDesktop session to request POINTER in addition to KEYBOARD when needed
and emit portal pointer motion/button/axis methods.

The session keeps one restore token/lifecycle. A compositor refusal is an unavailable backend, not a
daemon crash.

### macOS

Implement with the platform's supported synthetic pointer event API behind the same contract and
existing platform import guards.

### Windows

Implement with supported SendInput-style mouse events behind the same contract.

## Absolute vs relative motion

Relative motion is the minimum requirement for Head-Pointer.

Absolute motion is optional because:
- not all backends expose the same absolute coordinate semantics;
- multi-monitor/HiDPI makes absolute coordinates easy to get wrong;
- voice mouse grid may eventually need it.

Capabilities must tell the caller whether it is safe to use.

## Safety

A PointerSink executes already-authorized pointer intent. It does not decide whether intent is safe.

Safety remains above the sink:
- dwell detector decides when a click should occur;
- face switch emits an abstract switch event;
- destructive app commands use confirmation policy;
- global pause/kill/watchdog suppresses pointer production before it reaches the sink.

Backend failure should leave the pointer still.

## Alternatives considered

### Put mouse methods on InjectorBackend

Rejected. Text injection and pointer control have different permission, failure and capability
semantics. Expanding InjectorBackend would force every text backend to pretend it is also a pointer
backend.

### Head-Pointer owns platform commands

Rejected. It makes a pure accessibility feature platform-aware and guarantees duplication.

### One Wayland portal session per capability

Rejected. Multiple permission prompts/restore tokens would be confusing and fragile.

## Consequences

Positive:
- Head-Pointer stays pure and portable;
- Wayland consent/session code is reused;
- voice/gaze pointer features share the same output seam;
- contract tests can cover all backends.

Costs:
- platform bundle/factory work;
- coordinate semantics must be written precisely;
- portal capability negotiation becomes slightly more general.

## Implementation

See:
- `design/specs/eye-pointer-output.md`;
- #400–#403;
- `design/eye-control/TEST_PLAN.md`.
