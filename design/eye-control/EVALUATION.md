# Eye / camera control evaluation protocol

**Status:** programme-wide evaluation contract  
**Date:** 2026-09-22  
**Related:** [TEST_PLAN.md](TEST_PLAN.md), [DATA_SHARING.md](DATA_SHARING.md),
[PAPER_EVIDENCE.md](PAPER_EVIDENCE.md), [METRICS.md](METRICS.md)

This file answers four different questions that must not be collapsed into one benchmark:

1. **Does the code behave deterministically?** — automated CI.
2. **Does it work on this operating system / computer / camera?** — hardware QA.
3. **Does it work for different people, repeatedly?** — human evaluation.
4. **Can the resulting evidence support a paper claim?** — research protocol + ethics/consent gate.

A green CI run is not a usability study. One successful webcam demo is not cross-platform support.
A public GitHub test report is not automatically research consent.

## Evaluation ladder

### E0 — pure CI: every relevant PR

**Who:** nobody; fully automated.  
**Hardware:** virtual/runner only.  
**Paper eligible:** yes for software-correctness claims, with provenance.

Run on ordinary CI:

- pure gaze calibration math;
- confidence/fallback policy;
- implicit calibration candidate promotion/rejection;
- display coordinate transforms;
- Head-Pointer mapping/deadzone;
- dwell state machine;
- face-switch hysteresis/hold/refractory;
- Gesture Chords;
- global ACTIVE/PAUSED/FAULTED safety state;
- stale-signal watchdog;
- privacy/schema validators;
- fake camera/MediaPipe adapters;
- fake pointer backends;
- portal D-Bus protocol fakes.

**Goal:** logic and policy regressions are caught without a camera.

### E1 — OS matrix CI: every integration PR

**Who:** automated GitHub-hosted runners.  
**Hardware:** no usable representative webcam; OS/runtime only.  
**Paper eligible:** yes for build/install/platform-contract claims, not human performance.

Minimum matrix where supported:

- Ubuntu/Linux x86_64;
- Windows current hosted runner;
- macOS arm64/current runner;
- existing extra architecture legs where the repository workflow supports them.

Measure/record:
- install success;
- optional dependency resolution;
- lazy import behavior;
- tests;
- platform backend import/probe;
- permission/manifest static assertions;
- result schema validation.

Do **not** claim real camera/pointer usability from E1.

### E2 — deterministic synthetic trace replay

**Who:** automated.  
**Input:** checked-in numeric traces with no face images.  
**Paper eligible:** yes as regression/simulation evidence; label it synthetic.

Trace families:

- gaze drift / confidence drop;
- head jitter / motion / loss / recovery;
- dwell enter/reset/fire/re-arm;
- brow/mouth/blink blendshape-like normalized traces;
- talking-like mouth movement;
- face commit + simultaneous head-motion coupling;
- stale timestamps;
- topology change mid-session;
- grounded-target traces: target + semantic candidates + intent hint, replayed for
  grounded-correct, wrong target, ambiguity and abstention.

Primary purpose: make failures reproducible.

The grounded-target family has a harness (ADR-v2-151 P4, #445):

```sh
uv run python scripts/replay_grounding_trace.py            # print the report
uv run python scripts/replay_grounding_trace.py --check     # CI drift gate
```

It reads the traces in `tests/fixtures/grounding_traces/`, replays each case through the real
resolver under a window-only and a semantic-grounding strategy, and prints one deterministic
document; the committed copy is `tests/fixtures/grounding_replay_report.json`. Exit `0` valid,
`1` rule violation or drift, `2` unreadable. A trace with no cases is refused, because a
wrong-target rate computed over zero trials reads exactly like a perfect run. **The fixtures are
invented and no product threshold follows from their numbers** — that is RQ-G4's job, on real
desktops.

### E3 — one-machine hardware smoke

**Who:** contributor/tester.  
**Hardware:** real camera / OS / compositor.  
**Paper eligible:** engineering evidence; human performance only if a research protocol separately
covers the tester.

Scripted duration: approximately 10–20 minutes.

Minimum checks:
1. feature off -> camera unopened;
2. enable -> permission/status correct;
3. calibrate/recenter;
4. perform a small target/switch task;
5. deliberately lose camera/tracking;
6. verify no stale/repeated action;
7. pause/kill;
8. resume/re-arm;
9. disable -> camera released;
10. save privacy-safe result JSON/report.

Step 10 is a command rather than an instruction:

```bash
yazses eye-eval gaze_routing_4_pane --outcomes trials.json \
    --study-mode community_qa --camera-class integrated -o result.json
```

It generates the task from `yazses.eyeeval.tasks`, stamps the safe provenance
[METRICS.md](METRICS.md) asks for, validates the document against `yazses.eyeeval.schema`
and sweeps it for hostname/login/home-path/email **before** writing it, and prints
PASS/PARTIAL/FAIL/BLOCKED with the counts. `--synthetic` runs the same pipeline with no
camera, which is the E0/E1 leg. Nothing is uploaded and no flag would upload it; the tester
reads the file and attaches it themselves. A test that could not run is recorded with
`--blocked <reason>`, which reports every metric as explicitly missing rather than as zero.

### E4 — cross-computer replication

**Question:** does the same OS/software work on different physical machines/cameras?

For each supported platform/session, collect results on at least:
- two different computers;
- preferably two camera models/integrated cameras;
- at least one non-1.0 display scaling configuration where relevant.

Keep each result separate. Do not average machine latency across unlike hosts.

### E5 — cross-person replication

**Question:** does the calibration/control work for different people on comparable hardware?

This is where participant-specific behavior matters:
- gaze calibration;
- head neutral pose/range;
- face-switch threshold;
- speech/face coupling;
- comfort/fatigue.

If the results are intended for publication as human-participant evidence, E5 must run under the
research/ethics and consent process in [DATA_SHARING.md](DATA_SHARING.md) and
[PAPER_EVIDENCE.md](PAPER_EVIDENCE.md).

Community QA reports remain useful even when they are not paper-eligible.

### E6 — repeated-session / test-retest

**Question:** is the feature stable over time for the same person/computer?

Recommended:
- 3 sessions on different times/days when feasible;
- same software/config;
- record whether calibration was reused or repeated;
- report drift and false actions.

This distinguishes "worked once after calibration" from usable stability.

### E7 — controlled human study

Only needed for claims about:
- task completion;
- speed/throughput;
- error/false activation across people;
- usability;
- fatigue/comfort;
- comparison with another input method.

This is a research study, not an issue-tracker QA task.

Before recruitment:
1. freeze protocol and hypotheses/analysis;
2. obtain the required institutional/local ethics determination;
3. prepare informed consent;
4. define data retention/withdrawal;
5. version the software/test task;
6. decide what will and will not be shared publicly.

Current ACM venues require authors to explain the relevant ethics/review context for human-participant
work and comply with their research environment's requirements. Do not collect publication-intended
human data first and ask the ethics question afterward.

## Platform validation matrix

The programme should eventually cover these **distinct environments**, because "Linux" or "Windows"
alone hides the relevant differences.

| Bucket | Why it matters | Automated | Real hardware |
|---|---|---:|---:|
| Windows 11, normal Python/source install | camera + native pointer path | E1 | E3/E4 |
| Windows packaged/frozen build | camera capability/packaging differences | static | E3 |
| macOS Apple Silicon | camera permission + native pointer | E1 | E3/E4 |
| Ubuntu GNOME Wayland | portal pointer + Wayland target limits | E1 partial | E3/E4 |
| KDE Plasma Wayland | different portal/compositor behavior | E1 partial | E3/E4 |
| Linux X11 | existing gaze target + X11 pointer path | E1 partial | E3/E4 |
| HiDPI 150/200% | logical/physical coordinate conversion | synthetic | E3 |
| multi-monitor | topology/calibration invalidation | synthetic | E3 |
| integrated webcam | common user path | no | E3/E4 |
| external USB webcam | device/topology variation | no | E3/E4 |

A contributor does **not** need to test every bucket. Each small issue should ask for one bucket.

## Capability evaluation scripts

### Gaze routing task

One trial:
1. show 4 large target panes/regions;
2. prompt "look at target N";
3. user triggers the normal gaze-routing moment;
4. record intended target and resolved outcome.

Record:
- correct;
- wrong target;
- fallback/no-route;
- confidence bucket;
- calibration age;
- trial time.

Recommended QA block: 40 trials (10/target) after practice.

Primary metric:
`correct / all intended trials`.

Also report wrong-target and fallback separately; fallback is safer than wrong-target and must not be
collapsed into one "error".

### Head-Pointer task

Use large generated targets so the task does not depend on private desktop content.

For each target:
- target center;
- target width;
- pointer start;
- movement start/end;
- click outcome.

Record:
- completion;
- movement time;
- miss/overshoot;
- accidental click;
- pauses/recenters;
- tracking losses.

For research, the same data can support standard pointing analyses such as Fitts-style throughput,
but the analysis plan must be frozen before using that as a paper outcome.

### Face-switch task

Run blocks:
- deliberate gesture block;
- neutral/no-action block;
- normal speaking block when mouth gestures are tested.

Record:
- requested activation count;
- detected count;
- misses;
- extra/false activations;
- duration;
- activation latency;
- gesture name;
- configured thresholds/hold/refractory.

Primary safety metric:
**false activations/hour**, not only classifier accuracy.

### Hands-free workflow task

Use a fixed, non-sensitive demo application/fixture.

Example:
1. focus a text field;
2. dictate a short provided phrase;
3. move to a large button;
4. commit;
5. trigger a safe navigation command;
6. simulate camera loss;
7. pause;
8. resume;
9. finish task.

Record:
- task completion;
- total time;
- number of recovery actions;
- number/type of fallbacks;
- unintended actions;
- whether keyboard/mouse intervention was required.

## Replication structure

A result must identify a **replication cell**:

```text
software version
× OS/session
× computer
× camera
× display topology
× person/session (when human)
× feature/config
```

Do not report "n=10 tests" when all 10 are the same person on the same laptop unless the claim is
explicitly about repeated sessions.

For human studies, distinguish:
- **participants** — independent people;
- **sessions** — repeat observations;
- **trials** — repeated actions inside a session.

Never treat 400 gaze trials from one person as n=400 participants.

## What can be automated vs what cannot

| Question | Automatic? |
|---|---|
| algorithm/state transitions | yes |
| optional import/lazy loading | yes |
| schema/privacy redaction | yes |
| OS import/build compatibility | yes |
| synthetic false activation | yes |
| real camera opens | no, needs device |
| OS permission UI works | real OS/device |
| real gaze accuracy | human + camera |
| real head-pointer control | human + camera |
| false activations during natural behavior | human |
| fatigue/comfort | human report |
| useful hands-free workflow | human task |

## Failure reporting

A failed validation is a valuable result.

Testers select one:
- PASS;
- FAIL — reproducible;
- PARTIAL — some steps work;
- BLOCKED — dependency/permission/hardware prevents test.

Do not silently discard failures from paper-quality datasets. The exclusion rule must be written
before analysis, and technical invalidation (e.g. wrong version) must be distinguishable from a poor
feature result.

## Promotion gates

### Experimental

Requires:
- E0/E1 green;
- E2 traces;
- at least one E3 hardware smoke on each claimed platform;
- privacy/permission/status complete;
- global stop/recovery.

### Recommended

Additionally requires:
- E4 cross-computer evidence;
- E5 cross-person evidence;
- E6 stability where calibration matters;
- false-action metrics;
- accessibility/co-design evidence;
- all research claims backed by paper-eligible data collected under the appropriate protocol.



## Current no-code replication slots

The initial community QA matrix is now explicitly replicated:

- Windows: #428 + #429
- macOS: #430 + #431
- GNOME Wayland: #432 + #433
- KDE Wayland: #434 + #438
- X11: #435 + #439
- HiDPI/multi-monitor: #436 + #440
- test/retest same person/computer: #437

These issue pairs are engineering replication, not a substitute for the controlled human-study sample
defined by #425.
