# Contributing to eye / camera control

This guide is for a contributor who may know Python but **does not know YazSes** and may use a coding
agent.

Start here, not by searching the repository at random.

## 1. Pick work that is actually ready

Open [AGENT_TASKS.md](AGENT_TASKS.md) and choose an issue whose blockers are merged.

A good first contribution:
- documentation truth (#392);
- pure signal contracts (#393);
- PointerSink protocol (#400);
- false-activation harness (#409).

Do not start with a multi-platform backend or real-camera integration if this is your first YazSes PR.

## 2. Read exactly four things

For an implementation issue:

1. the issue;
2. its linked ADR;
3. its linked implementation spec;
4. the closest existing test named in the issue.

Only expand from there when the issue/spec points you to another seam.

## 3. Using a coding agent

Give the agent:
- the issue body;
- the ADR path;
- the spec path;
- allowed paths;
- exact definition-of-done command.

Tell it explicitly:
- do not broaden scope;
- do not add dependencies without the spec;
- do not make hardware/network required for ordinary CI;
- do not change feature tier/status unless the issue says to.

The human contributor remains responsible for reading the diff and verifying the acceptance criteria.

## 4. Test from the inside out

Run:
1. pure/narrow tests;
2. adapter tests;
3. feature-wiring tests;
4. full suite/lint/type-check where feasible;
5. hardware smoke only after hermetic tests pass.

Do not use a successful webcam demo as a substitute for unit tests.

## 5. Evidence rules

A hardware report should state environment and derived metrics. It should **not** contain:
- face images/video;
- raw landmarks;
- diagnosis/disability details;
- typed private content;
- window titles/screenshots unless independently necessary and intentionally shared.

Use the eye-control device-report issue template for live tests.

## 6. PR shape

One issue normally means one PR.

A PR description should include:

```text
Closes: #<issue>
ADR: design/adr/<...>
Spec: design/specs/<...>

Narrow CI:
<commands + result>

Hardware evidence:
not required / pending / link

Privacy:
no raw frame persistence
no new runtime network path
camera remains dormant when disabled
```

## 7. When to stop and ask for design change

Stop implementation when:
- the spec does not define units/coordinate space;
- a required action is not exposed by the named protocol;
- you must choose a new default threshold;
- a destructive action bypasses confirmation;
- a new dependency/package permission seems necessary;
- fixing the issue requires touching unrelated subsystems.

Open/comment a design gap instead of guessing. A small incomplete PR is better than a second
architecture hidden inside implementation code.

## 8. Real-user accessibility work

Treat reports as evidence, not as "user error." Record:
- the task;
- setup;
- observed failure;
- metric;
- recovery.

Do not infer medical capability from a failed test. The purpose is to learn whether the interaction
works in that environment.

## 9. Done means traceability is updated

If your PR makes a capability runtime-reachable, update:
- relevant spec status;
- `design/eye-control/README.md`;
- `TRACEABILITY.md`;
- user docs/feature registry when applicable.

The tracker and documentation are part of the feature.
