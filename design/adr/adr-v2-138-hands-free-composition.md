# ADR-v2-138 — Hands-free mode is a composition preset with one global safety state

**Status:** Proposed (2026-09-22)  
**Context links:** [[adr-v2-010-gaze-routed-dictation]], [[adr-v2-030-voice-mouse-grid]], [[adr-v2-043-gesture-chords]], [[adr-v2-052-head-pointer]], [[adr-v2-135-shared-camera-perception]], [[adr-v2-136-pointer-output-boundary]], [[adr-v2-137-face-switch-intent]]

## Context

YazSes is accumulating the components of hands-free desktop operation:

- voice text/commands;
- gaze target/context;
- Head-Pointer;
- dwell;
- face/EMG/mouth switches;
- voice mouse grid;
- read-back and notifications.

The easiest implementation mistake is to add a new "hands-free daemon mode" with its own event loop,
config, confirmation and platform logic. That would duplicate the existing pipeline and make every
future feature decide whether it belongs to ordinary YazSes or hands-free YazSes.

There is also a safety problem. Continuous pointer/switch controls must share an immediate way to stop
actions even when the pointer itself is misbehaving.

## Decision

`handsfree` is a **configuration composition/preset**, not a second pipeline.

Enabling it configures ordinary capabilities and starts only the shared services those capabilities
need.

Conceptually:

```text
handsfree preset
  -> gaze config
  -> headpointer config
  -> face/switch config
  -> pointer backend
  -> existing speech/command pipeline
  -> existing confirmation/notification system
```

No second STT, command dispatcher, injector, camera source or confirmation stack is introduced.

## Global safety state

All continuous hands-free input obeys one high-level state:

- **ACTIVE** — configured inputs may emit actions;
- **PAUSED** — sensing may remain available for status, but pointer/switch actions are suppressed;
- **FAULTED** — stale/unavailable sensor/backend; actions suppressed until explicit recovery/re-arm.

The implementation may use simpler internal names, but the behavior is required.

## Kill/pause path

At least one stop path must be independent of the pointer being controlled.

Examples:
- voice command;
- physical keyboard key;
- configured switch;
- tray/menu action.

A user must not have to accurately point at a tiny UI control with the malfunctioning Head-Pointer in
order to stop Head-Pointer.

## Recovery hierarchy

When a preferred modality fails:

1. stop actions from the failed/stale source;
2. keep unaffected modalities available;
3. fall back only to behavior that cannot increase consequence;
4. explain the degradation;
5. require explicit re-arm where recovery could otherwise fire immediately.

Never replay the last pose, last switch event or last gaze target.

## Preset semantics

The preset may provide recommended **experimental** starting values, but the actual source-of-truth
remains the underlying feature config.

Disabling the preset should:
- stop/pause the components it enabled;
- release continuous camera consumers where no other feature needs them;
- not erase the user's calibration/mapping data.

## Alternatives considered

### Dedicated hands-free daemon/pipeline

Rejected. It duplicates core behavior and will drift.

### No global safety state; each feature owns pause

Rejected. Multiple independently active controls create inconsistent recovery and no single emergency
stop.

### Turn every modality off on one sensor failure

Rejected. Losing face tracking should not disable speech. Failure containment is a core benefit of
multimodality.

## Consequences

Positive:
- less duplicate code;
- existing command safety remains authoritative;
- one pause/kill model for contributors and users;
- components can be tested independently and composed late.

Costs:
- preset/config ownership must be precise;
- daemon status must expose component state;
- startup/shutdown order needs integration tests.

## Implementation

See:
- `design/specs/eye-handsfree-bundle.md`;
- #410;
- programme safety/observability issues;
- `design/eye-control/TEST_PLAN.md`.
