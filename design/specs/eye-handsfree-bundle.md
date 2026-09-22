# Spec: Hands-Free Bundle — Compose Voice, Gaze, Head Pointer and Switch Inputs Safely

| Field | Value |
|---|---|
| **ID** | spec-eye-handsfree-bundle |
| **Status** | Proposed |
| **Date** | 2026-09-22 |
| **Modules** | feature/config orchestration; daemon status/control; existing component modules |
| **Related** | ADR-v2-138, ADR-v2-010, ADR-v2-052, ADR-v2-137 |
| **Issues** | #410 plus safety/permissions/observability/co-design tasks |

## Goal

Provide one understandable way to enable and operate a hands-free YazSes configuration while reusing
existing components rather than creating a parallel pipeline.

## Non-goals

- no new STT engine;
- no new command dispatcher;
- no second camera loop;
- no hidden cloud service;
- no single mandatory activation modality;
- no claim that every user should use the same gesture/dwell defaults.

## Composition

A hands-free preset configures ordinary capabilities:

| Role | Candidate |
|---|---|
| Text bandwidth | speech |
| Target/context | gaze |
| Continuous pointer | Head-Pointer |
| Discrete commit | face switch / dwell / EMG / voice |
| Precision fallback | Voice Mouse Grid |
| Feedback | tray/notification/read-back |
| Destructive safety | existing confirmation policy |

Users may enable a subset.

## Global state

The bundle exposes:
- ACTIVE;
- PAUSED;
- FAULTED.

### ACTIVE

Component actions allowed subject to their own confidence/safety gates.

### PAUSED

Continuous pointer/switch actions suppressed. Ordinary non-hands-free dictation may remain usable.

### FAULTED

A required active component has stale/unavailable state; related actions suppressed until recovery.
No automatic replay/re-arm.

## Pause / emergency stop

Provide at least one control independent of pointer accuracy.

At experimental release, document at least two stop paths where platforms allow it (for example voice
and keyboard/tray).

Global pause:
- clears dwell progress;
- clears pending face gesture state;
- suppresses pointer motion/click;
- does not delete calibration;
- keeps enough sensing/status to explain recovery if privacy/config allows.

## Startup order

1. load/validate config;
2. identify enabled components;
3. validate optional deps/model;
4. establish permissions/backends;
5. start shared perception if needed;
6. start consumers;
7. remain PAUSED/FAULTED rather than partially firing if a critical component is unavailable;
8. expose state to tray/status.

Speech-only fallback must remain available when optional camera controls fail, unless the user
explicitly configured otherwise.

## Shutdown

Reverse safely:
- suppress actions first;
- stop consumers;
- release camera source when last consumer;
- close pointer backend;
- leave ordinary daemon shutdown intact.

## Failure matrix

| Failure | Required behavior |
|---|---|
| camera unavailable | camera controls unavailable; speech survives |
| head pose stale | pointer stops; no last delta |
| face switch stale | switch stops; no last event |
| pointer backend denied | no pointer actions; gaze/speech may remain |
| display topology change | gaze routing pauses until geometry/calibration valid |
| model unavailable | actionable status; no repeated network loop |
| permission denied | explain exact permission/fallback |

## Config ownership

`handsfree` preset does not create duplicate hidden settings.

Implementation can:
- set/enable underlying configs;
- remember which values were preset vs user-overridden;
- expose composed state.

Disabling bundle does not erase calibration.

## Doctor/status

Must report:
- overall state;
- camera/perception source state;
- head tracking state;
- face switch state;
- pointer backend;
- permissions;
- calibration valid/stale;
- global pause state;
- actionable reason for fault.

No face landmarks/biometric values.

## Accessibility UI

Settings/docs should expose:
- enable/disable;
- pause/kill;
- recenter;
- dwell on/off;
- switch mapping;
- confidence/threshold advanced controls;
- current status;
- recalibration.

The first experimental release may be CLI-first only if every required action is documented and an
accessible stop path exists. Recommended status requires a usable non-terminal control surface.

## Acceptance scenario

Without touching a mouse after start:
1. activate/recenter safely;
2. target a text destination;
3. dictate text;
4. move pointer to a large control;
5. commit/select;
6. obscure/lose camera and observe no phantom action;
7. pause;
8. resume/re-arm;
9. request a destructive action and receive confirmation;
10. disable/quit and verify camera/pointer release.

Automated integration uses fakes; live evidence repeats on real hardware.

## Release gates

Experimental:
- all component hermetic tests;
- global stop;
- permissions/doctor;
- one hardware report;
- setup/troubleshooting.

Recommended:
- multi-environment field evidence;
- false activation/click metrics;
- accessibility co-design/usability review;
- fatigue observations;
- risk register blockers resolved.
