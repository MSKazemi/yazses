# Eye / camera control programme governance

This file defines the **management contract** for the eye/camera programme. It answers a question the
code cannot: what evidence and design artifacts must exist before an idea becomes an implementation
task, and what must be true before an experimental accessibility control is recommended to users.

Parent epic: #102  
Milestone: **Hands-free — perception & accessibility** (#10)  
Traceability epic: #377

## The artifact chain

No eye/camera capability skips a layer:

```text
problem / user need
   -> research evidence + known limits
   -> ADR (only when an architectural choice is needed)
   -> implementation spec
   -> agent-sized GitHub issue
   -> code + hermetic tests
   -> live hardware evidence
   -> experimental release
   -> recommendation gate
```

An ADR is **not** a schedule. A spec is **not** proof that something works. A closed implementation
issue is **not** evidence that camera behavior is usable on real people/hardware.

## Required artifact by change type

| Change | Research | ADR | Spec | Issue | Hardware evidence |
|---|---|---|---|---|---|
| Pure bug in existing detector | existing evidence sufficient | no | existing spec | yes | if behavior is hardware-dependent |
| New backend for existing protocol | source/API study | only if protocol changes | yes/update | yes | yes |
| New camera-derived signal | yes | yes if shared architecture changes | yes | yes | yes |
| Threshold/default change | measurement required | usually no | update | yes | **required** |
| New destructive action mapping | safety/error-cost review | yes/update | yes | yes | required before recommendation |
| Documentation correction | no | no | no | yes if non-trivial | no |
| New optional hardware family | yes + licensing | likely | yes | yes | required |
| Promote experimental -> recommended | field evidence | no new ADR unless policy changes | update | promotion issue | **required** |

## Status vocabulary

Every capability is exactly one of:

- **RESEARCH** — evidence/question exists; no implementation commitment.
- **DESIGNED** — ADR/spec exists; not yet reachable.
- **CORE** — tested core exists but complete runtime path does not.
- **EXPERIMENTAL** — reachable, documented and tested, but real-world evidence is still limited.
- **RECOMMENDED** — field evidence supports defaults and failure behavior.
- **DEFERRED** — deliberately not active; reason is written.
- **RETIRED** — no longer supported; migration/fallback documented.

`LIVE` in the programme audit means runtime-reachable. It is orthogonal to whether the feature is
experimental or recommended.

## Gate 0 — problem is real

Required:
- concrete user task;
- current failure/cost;
- why existing YazSes modes do not already solve it;
- measurable success criterion.

Do not open an implementation issue for "camera can detect X" without a user task.

## Gate 1 — evidence and scope

Required:
- prior art;
- honest sensor accuracy/latency limitations;
- ordinary-laptop/offline feasibility;
- privacy effect;
- explicit non-goals.

For webcam gaze, the programme-wide scope rule is already settled: **coarse targeting, not caret
precision**.

## Gate 2 — architectural decision

Write/supersede an ADR only when the work decides something that future implementations should not
re-decide independently.

Current programme ADR set:
- ADR-v2-010 — gaze routing / point-and-speak;
- ADR-v2-043 — Gesture Chords;
- ADR-v2-052 — Head-Pointer;
- ADR-v2-145 — shared camera perception;
- ADR-v2-146 — pointer-output boundary;
- ADR-v2-147 — face gesture as an intent-bearing switch;
- ADR-v2-148 — hands-free bundle is composition, not a second pipeline;
- ADR-v2-149 — gaze calibration coordinate space and invalidation;
- ADR-v2-150 — community QA and human research are separate evidence classes;
- ADR-v2-151 — coarse target -> semantic UI entity grounding (proposed).

## Gate 3 — implementation-ready spec

A spec must answer all of these before an `agent-ready` label is justified:

1. exact integration seam and files/protocols;
2. inputs/outputs and units;
3. lifecycle/state machine;
4. config keys/defaults;
5. lazy dependency rule;
6. privacy/data retention;
7. failure/fallback behavior;
8. platform differences;
9. acceptance criteria;
10. exact narrow tests;
11. live-hardware evidence required after CI;
12. non-goals.

If an implementer must choose a new policy mid-PR, the spec is incomplete.

## Gate 4 — agent-sized task

Use `.github/ISSUE_TEMPLATE/agent_task.yml` semantics even when an issue is created programmatically.

Every implementation issue must contain:
- one-sentence goal;
- explicit non-goals;
- exact integration seam;
- optional dependency/lazy-load statement;
- Given/When/Then acceptance criteria;
- required tests;
- docs update;
- definition-of-done command;
- size;
- blockers;
- hardware requirement.

**One issue = one reviewable PR** unless the issue explicitly says it is a research/measurement
collector.

## Gate 5 — implementation acceptance

Required:
- narrow tests green;
- no unexpected optional imports;
- no new frame persistence/network egress;
- graceful disabled/failure path;
- feature registry/docs truth agree;
- config validation;
- existing behavior regression tests.

## Gate 6 — experimental release

Required:
- setup and troubleshooting docs;
- `doctor`/status can explain unavailable dependencies/permissions;
- feature can be disabled without a restart trap or stuck sensor;
- visible/observable camera-active state where continuous sensing is used;
- an emergency pause/kill path for continuous pointer/switch behavior;
- at least one live-hardware smoke report.

## Gate 7 — recommended defaults

Required:
- more than one real environment/device;
- error metric appropriate to modality;
- false-activation rate where actions can fire;
- accessibility review;
- fatigue/recovery observation for continuous controls;
- no unresolved high-severity risk in [RISK_REGISTER.md](RISK_REGISTER.md);
- defaults justified by evidence.

## Issue-label policy

The repository already has useful labels. Use existing labels rather than inventing a parallel eye
taxonomy.

### Required/common existing labels

| Meaning | Label |
|---|---|
| Programme/domain | `accessibility` |
| Code behavior change | `enhancement` |
| Contributor welcome | `help wanted` |
| Fully specified for coding agents | `agent-ready` |
| Python implementation | `python` |
| Documentation-only | `documentation` |
| New contributor suitable | `good first issue` |
| Needs measurement | `measurement-wanted` |
| Cannot finish validation without device | `hardware-required` |
| Evidence/design question | `research` |
| Critical active dependency | `priority:p1` |
| Truly small task (<~150 lines) | `size:s` |

Do **not** put `agent-ready` on an issue until its prerequisite ADR/spec is present and no unresolved
design choice remains.

### Programme grouping

Until a dedicated `eye-control` label exists, use:
- the `[EYE-...]` title ID;
- milestone #10;
- `accessibility`;
- the canonical issue map in `AGENT_TASKS.md`.

That gives three independent ways to find the work without relying on a new repository label.

## Readiness label state machine

Issue readiness is explicit and reversible:

```text
PLANNED
  -> READY FOR HUMAN CONTRIBUTOR   (`help wanted`)
  -> READY FOR BEGINNER            (+ `good first issue`)
  -> READY FOR CODING AGENT        (+ `agent-ready`)
  -> EXECUTION TRIGGERED            (provider-specific label such as `jules`, only when intentionally used)
```

Rules:

- `PLANNED` issues remain open for visibility but carry none of `help wanted`, `good first issue`,
  or `agent-ready`.
- `help wanted` means the task can actually be started from `main` now.
- `good first issue` is a subset of `help wanted`; it must never be placed on a blocked slot.
- `agent-ready` is a subset of ready code/document work and requires all design dependencies to be
  merged and available from `main`.
- Human hardware evidence can be `help wanted` / `good first issue` when READY, but never
  `agent-ready`.
- A provider execution label is not a planning label. Never use it merely to mean "agent-friendly".

Issue bodies should begin with a short **Current status** banner while PLANNED so readiness is visible
without interpreting labels.

When a blocker reopens or a design contract moves back to Proposed/unstable, remove readiness labels
again.

## Priority policy

`priority:p1` means **on the critical dependency path**, not "interesting".

For this programme, P1 applies to:
- shared signal/source foundation;
- pointer-output boundary;
- permission/packaging correctness;
- Head-Pointer runtime foundation;
- face-switch detector/adapter;
- global safety/kill behavior;
- hands-free bundle integration.

Field studies and dedicated tracker research are important but are not implementation blockers for the
first experimental webcam/head-control release.

## Size policy

Use `size:s` only when a normal implementation should remain under about 150 changed lines excluding
tests/docs. Do not label a 2–3 hour multi-platform backend `size:s` merely because no `size:m`
label exists.

## Dependency policy

Issue bodies must name blockers by issue number. A blocked issue can remain open, but should not be
advertised as ready-to-code until its blocker is merged.

The dependency graph in [TRACEABILITY.md](TRACEABILITY.md) is the canonical programme graph.

## Close policy

Close implementation issues only when:
- acceptance criteria are met;
- required code/tests are merged;
- docs/status truth is updated.

Do not close a hardware-validation collector because one successful machine report arrived. Define
the target sample/environment coverage in the issue.

## Change control

If implementation reveals the design is wrong:
1. stop expanding the PR;
2. update/supersede the ADR/spec;
3. update child issue acceptance criteria;
4. only then resume implementation.

That is cheaper than letting an agent silently create a second architecture.


## Evidence classes and paper eligibility

Use the evaluation levels in [EVALUATION.md](EVALUATION.md):

- **E0/E1** — automated CI/platform contract;
- **E2** — synthetic trace replay;
- **E3** — one-machine human-operated hardware smoke;
- **E4** — same platform on different computers;
- **E5** — different people;
- **E6** — repeated sessions/test-retest;
- **E7** — controlled human study.

### Paper-use rule

- Automated and synthetic data may support software/system claims when provenance is complete.
- Public GitHub community QA is **engineering evidence by default** and is not automatically
  participant data for a paper.
- Human-performance paper claims use data collected under the named research protocol after the
  applicable ethics/review determination and participant information/consent.
- If a community tester later joins the study, collect a new research session rather than
  retroactively relabeling the public issue.

### Independent units

For reporting:
- machine count is not participant count;
- session count is not participant count;
- trial count is not participant count.

A result with 400 trials from one person remains one participant for participant-level claims.

### Validation coverage for recommended status

Before an eye/camera capability becomes recommended, the programme should have:
- at least two physical computers for every claimed major platform/session bucket where practical;
- cross-person evidence for person-calibrated behavior;
- repeat-session evidence for calibration/drift-sensitive behavior;
- negative/failure results preserved;
- the applicable research protocol for any human-performance paper claim.

The exact research sample size is determined by the frozen study/analysis plan, not by this governance
document.
