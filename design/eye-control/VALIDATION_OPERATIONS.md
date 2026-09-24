# Eye / camera validation operations

This file governs **how validation work is opened, claimed, completed and expanded**. It exists so
the repository does not accumulate dozens of hardware issues that are impossible to run yet, while
also preventing one successful laptop from becoming the entire evidence base for an OS.

Related:
- [VALIDATION_MATRIX.md](VALIDATION_MATRIX.md)
- [BEGINNER_TESTING.md](BEGINNER_TESTING.md)
- [EVALUATION.md](EVALUATION.md)
- [DATA_SHARING.md](DATA_SHARING.md)
- [GOVERNANCE.md](GOVERNANCE.md)

## Two kinds of contributor work

### Code / fixture work

Examples:
- evaluation JSON schema;
- generated test target fixture;
- result validator;
- synthetic trace harness;
- CI workflow.

These belong in the normal code/document contribution pipeline and may be `agent-ready` when their
design blockers are merged.

### Human / hardware evidence

Examples:
- camera permission actually appeared on Windows;
- GNOME Wayland portal motion worked;
- gaze chose the correct pane;
- a face switch fired while speaking;
- 150% scaling invalidated calibration correctly.

These are never cloud-agent-certifiable. A machine can prepare the harness; a human must observe the
real hardware result.

## Validation slot lifecycle

A validation slot is one bounded human task.

States:

```text
PLANNED
  -> READY
  -> CLAIMED
  -> REPORTED
       -> PASS
       -> PARTIAL
       -> FAIL
       -> BLOCKED
  -> CLOSED
```

### PLANNED

The matrix says evidence will eventually be needed, but the runtime/harness is not available.

Do not advertise it as a good first issue yet.

### READY

A slot becomes READY only when:

- the relevant feature path is runtime-reachable on that platform;
- the local evaluator/task fixture exists;
- the privacy-safe output schema exists;
- the stop/recovery path required by that test is implemented;
- the exact test pack is frozen/versioned;
- the issue body names the required version/blockers.

### CLAIMED

One contributor says they are running that exact slot.

A/B slots should usually be claimed by different people/computers.

### REPORTED

A report is complete when it includes the required provenance + generated metrics and explicitly says
PASS / PARTIAL / FAIL / BLOCKED.

FAIL/PARTIAL/BLOCKED are valid completion outcomes.

## When to create A/B slots

Create A/B slots when a platform/capability is ready for independent replication.

A = first independent physical environment.  
B = another physical computer and preferably another person.

Do not ask the same contributor to fill both merely to close issues.

For person-calibrated behaviors, two computers alone are not enough for recommendation; use the
human/research evidence ladder separately.

## Do not create the full Cartesian product up front

The matrix can eventually contain:

```text
test pack × OS/session × computer × person × camera × display topology
```

That does **not** mean GitHub should contain hundreds of open issues.

Open only:
- the next A/B platform slots whose runtime is ready;
- one or two special topology/device slots;
- a test/retest slot when stability matters.

Keep future cells in the machine-readable matrix/roadmap until ready.

## Naming convention

Hardware validation issue:

```text
[EYE-QA-<ENV>-<SLOT>] <PACK>: <plain-language task>
```

Examples:
- `[EYE-QA-WIN-A] T0: camera lifecycle on Windows 11`
- `[EYE-QA-GNOME-B] T2: Head-Pointer large-target replication`
- `[EYE-QA-HIDPI-A] T5: calibration topology check`

The title itself carries platform/pack identity because this repository does not currently rely on a
large platform-label taxonomy.

## Required labels

Human hardware slot:
- `accessibility`
- `help wanted`
- `good first issue` when genuinely beginner-safe
- `measurement-wanted`
- `hardware-required`
- `size:s` when <= roughly one short session

Do **not** apply:
- `agent-ready` — the evidence itself cannot be produced by a cloud coding agent;
- `jules` — it is an execution trigger and would be inappropriate for human evidence.

Code/evaluator task:
- `accessibility`
- `enhancement`
- `help wanted`
- `python` when appropriate
- `agent-ready` only when all design blockers are merged
- `priority:p1` only for the critical foundation, not every measurement helper.

## Slot blockers

Every READY issue names blockers explicitly.

Examples:
- T0 depends on actual camera runtime + permission/status behavior.
- T1 depends on the standard 4-target fixture and local evaluator.
- T2 depends on Head-Pointer runtime + PointerSink.
- T3 depends on face-switch runtime.
- T4 depends on global pause/stale-signal watchdog.
- T5 depends on coordinate/topology invalidation.
- T6 depends on semantic candidate/resolver adapters.
- T7 depends on the composed hands-free runtime.

If a blocker is not merged, the issue stays PLANNED and should not tell a beginner to invent manual
workarounds.

## Result ownership

Community QA results are engineering evidence.

They may support:
- platform support;
- bug reproduction;
- release promotion;
- performance envelopes by host.

They do not automatically become human-research participant data. ADR-v2-150 remains authoritative.

## Contributor credit

A useful FAIL/BLOCKED report is still a contribution.

Where the project contributor-credit process supports issue-only/testing contributions, preserve that
credit. Do not make a volunteer fix the bug they found in order to count as a contributor.

## Campaign task-finder integration

YazSes already has a generated contributor task finder backed by `campaign/tasks.json`.

Eye validation should appear there only after the evaluator/result-validation path is stable enough
that the campaign task can name:

- exact environment;
- exact time estimate;
- no coding required;
- exact evidence to collect;
- a bounded durable project output or validated report path;
- an executable validation command where the campaign contract requires one.

Until then, the dedicated no-code issues + BEGINNER_TESTING guide are the source of truth.

A follow-up implementation task should integrate READY eye-validation slots into the campaign finder
without weakening the campaign schema or pretending hardware evidence is cloud-agent-ready.

## Coverage dashboard

The project should be able to answer, without reading every issue manually:

- which T0–T7 packs are implemented;
- which OS/session cells are READY;
- which A/B slots are unclaimed/claimed/reported;
- PASS/PARTIAL/FAIL/BLOCKED count;
- how many distinct physical hosts are represented;
- how many results are repeated sessions vs independent people;
- which claims still lack independent replication.

That dashboard is operational engineering metadata, not a paper analysis.

## Closing rules

Close a no-code slot when:
- the required version/test pack was used;
- required provenance is present;
- generated metrics are present or BLOCKED reason explains why not;
- privacy rules are respected.

Do not reopen a FAIL solely because it failed. Open/attach the engineering bug separately and keep the
failed validation as evidence.

If a later release changes the relevant subsystem materially, open a new versioned validation cell
rather than editing history to imply the old result tested the new implementation.


## Public report form gate

The issue form is **not** the authority that makes a test READY.

Before a contributor uses either public eye/camera report form:
1. a parent validation/measurement issue must be READY or explicitly request hardware evidence;
2. that issue names the test pack/protocol version;
3. the contributor links the parent issue in the form;
4. the resulting public report is classified as `community_qa`.

A form must not auto-apply `good first issue`; beginner readiness belongs to the parent slot because
the same form can serve both mature and complex hardware checks.

Research-participant data never uses the public GitHub form as its canonical collection path.
