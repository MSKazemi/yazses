# Eye / camera control — current programme status

**Snapshot:** 2026-09-23  
**Parent epic:** #102  
**Planning PR:** #413  
**Milestone:** Hands-free — perception & accessibility (#10)

This page is the short operational front door. It answers:

- what YazSes already has;
- what the programme is trying to add;
- what can be worked on now;
- what is blocked;
- what evidence is required before stronger claims are made.

For authoritative detail, follow the linked ADR/spec/issue. This page is intentionally a snapshot and
must not override an issue's live blocker/status banner.

## One-sentence vision

Use ordinary local camera signals — coarse gaze, head pose and deliberate face gestures — as
**optional accessibility inputs** that compose with YazSes voice control, while preserving an
independent stop path, explicit fallback/abstention, local processing and privacy-safe evaluation.

The programme does **not** redefine webcam gaze as precision eye tracking.

## What exists today

| Capability | Current state | Evidence / limitation |
|---|---|---|
| Gaze routing / Glance-Type | runtime-reachable | coarse window/pane targeting; existing gaze backend/tests |
| Gaze + speech deixis | runtime-reachable | coarse target context, not arbitrary semantic UI control |
| Implicit gaze calibration core | core exists | runtime observation/apply path is not complete |
| Head-Pointer mapping/dwell core | core exists | full shared-camera + pointer-output runtime is not yet complete |
| Gesture Chords core | core exists | camera-derived face/head tokens are not yet fully wired |
| Face-gesture switch | designed/planned | detector + activation adapter not yet runtime-complete |
| Shared one-owner camera perception | designed in #413 | implementation starts after planning merge |
| Cross-platform PointerSink | designed in #413 | platform backends are child tasks |
| Global hands-free safety state | designed in #413 | implementation child task |
| Grounded semantic UI target refinement | proposed/design | semantic-first; no screenshot/OCR/VLM tier by default |
| Human/paper evaluation | designed only | no controlled participant study should be implied yet |

## What is READY right now?

A task is startable only if its issue has:
- a **READY** banner; and
- `help wanted`.

For coding-agent work, `agent-ready` is additionally required.

### Wave 0

At this snapshot:

- **#392 EYE-DOC-001** — READY, small documentation-truth correction.

Everything else in the programme remains dependency-driven. Do not infer readiness from an open issue
alone.

## Root gate

**#413 must merge before the new programme contracts are present on `main`.**

After #413 merges, **#493** performs the controlled Wave-1 readiness transition. It must not activate
downstream tasks whose exact blocker is still open.

Expected first Wave-1 candidates, subject to the live issue check:

| Issue | Work | Expected readiness after #413 |
|---|---|---|
| #393 | pure perception signal contracts | human + coding-agent ready |
| #400 | PointerSink protocol/fake | human + coding-agent ready |
| #421 | evaluation result schema/validator | human + coding-agent ready |
| #441 | semantic target/candidate contracts | human + coding-agent ready |
| #414 | camera permission/packaging contract | human-ready; agent only if platform policy is fully frozen |
| #415 | topology/HiDPI foundation | human-ready; agent after seam check |
| #417 | global safety/watchdog foundation | human-ready; agent after seam check |
| #425 | research protocol/ethics gate | human research/design only |
| #427 | data-sharing language review | beginner documentation task |
| #449 | beginner-guide usability review | beginner documentation task |
| #454 | validation registry/validator | human + coding-agent ready |

## Dependency spine

The implementation spine is intentionally narrow:

```text
#413 planning merge
   |
   +--> #393 perception contracts
   |       -> #394 camera lifecycle
   |       -> #395 derived gaze/head/face signals
   |       -> #396 gaze migration
   |       -> gaze/head/face runtime children
   |
   +--> #400 PointerSink protocol
   |       -> #401 X11
   |       -> #402 macOS/Windows
   |       -> #403 Wayland portal
   |       -> #404 Head-Pointer runtime
   |
   +--> #421 eval schema
   |       -> #422 deterministic task fixtures
   |       -> #423 local privacy-safe evaluator
   |       -> #424 cross-OS CI evaluation
   |       -> hardware validation slots become eligible
   |
   +--> #441 semantic contracts
   |       -> #442 resolver
   |       -> #443 integration
   |       -> #445 deterministic grounding evaluation
   |
   +--> #454 validation registry
           -> #455 coverage dashboard
           -> #456 contributor task-finder integration
```

## Hardware validation is intentionally not READY yet

Issues #428–#440 describe the first A/B hardware matrix:

- Windows A/B;
- macOS A/B;
- GNOME Wayland A/B;
- KDE Wayland A/B;
- Linux X11 A/B;
- HiDPI/multi-monitor A/B;
- repeated-session gaze stability.

They stay **PLANNED** until:
- #423 exists;
- the relevant runtime capability exists;
- stop/recovery behavior required by that pack exists;
- the named test fixture/version is frozen.

When READY, a hardware task may regain:
- `help wanted`;
- `good first issue`;
- never `agent-ready`.

## Evaluation ladder

| Level | Meaning |
|---|---|
| E0 | pure unit/state logic |
| E1 | cross-OS build/import/platform-contract CI |
| E2 | deterministic synthetic trace replay |
| E3 | one-machine real hardware smoke |
| E4 | same platform on another physical computer |
| E5 | different people |
| E6 | repeated-session / test-retest |
| E7 | controlled human-participant study |

Green E0–E2 evidence does not prove camera usability. One E3 laptop does not prove platform support.
Many trials from one person do not become many participants.

## Canonical test packs

- **T0** — camera lifecycle / permission / stop / release;
- **T1** — coarse four-target gaze;
- **T2** — large-target Head-Pointer;
- **T3** — deliberate face-switch + neutral/speaking exposure;
- **T4** — pause/kill/loss/recovery safety;
- **T5** — HiDPI/multi-monitor topology;
- **T6** — semantic grounding: correct/wrong/ambiguous/abstain;
- **T7** — composed hands-free demo workflow.

See [VALIDATION_MATRIX.md](VALIDATION_MATRIX.md).

## Minimum engineering evidence before recommendation

For each claimed major OS/session where practical:

- two physical computers;
- preferably different people for A/B;
- failures preserved, not filtered out;
- safety/recovery test;
- relevant false-action metric;
- multi-monitor/scaling evidence where coordinates matter;
- repeated-session evidence where calibration/drift matters.

This is an engineering release gate, **not** a scientific sample-size rule.

## Paper / research boundary

The result source class must remain explicit:

- `ci`;
- `synthetic`;
- `community_qa`;
- `research`.

Public GitHub QA is `community_qa` by default.

A public tester:
- is not automatically a research participant;
- is not retroactively enrolled by relabeling a JSON file;
- may separately volunteer for a later study, which collects a new session under the named research
  protocol.

Human-performance paper claims require the research path in
[PAPER_EVIDENCE.md](PAPER_EVIDENCE.md) and [DATA_SHARING.md](DATA_SHARING.md).

## Public data rule

Default community reports share derived technical evidence only.

Never request in a public issue:
- raw face/video frames;
- raw private screen content;
- private dictated text/audio;
- diagnosis/medical records;
- email/phone/address;
- hostnames or hardware serials;
- passwords/tokens.

## Definition of programme progress

Progress is **not** measured by issue count.

Useful milestones are:

1. design contract merged;
2. pure contract implemented and tested;
3. runtime path reachable;
4. local evaluator available;
5. safety/stop path works;
6. first real hardware result;
7. independent A/B replication;
8. cross-person/repeated-session evidence where needed;
9. experimental release;
10. recommendation gate supported by evidence.

## Where to go next

- contributor: [CONTRIBUTING.md](CONTRIBUTING.md)
- beginner/no-code tester: [BEGINNER_TESTING.md](BEGINNER_TESTING.md)
- implementation issue map: [AGENT_TASKS.md](AGENT_TASKS.md)
- architecture/delivery sequence: [ROADMAP.md](ROADMAP.md)
- evaluation: [EVALUATION.md](EVALUATION.md)
- test packs: [VALIDATION_MATRIX.md](VALIDATION_MATRIX.md)
- metrics: [METRICS.md](METRICS.md)
- privacy/data sharing: [DATA_SHARING.md](DATA_SHARING.md)
- risk/release blockers: [RISK_REGISTER.md](RISK_REGISTER.md)
- traceability: [TRACEABILITY.md](TRACEABILITY.md)
