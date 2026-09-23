# Eye-control planning PR review guide

**PR:** #413 — `design: make eye / camera control an executable roadmap`

This PR is intentionally design-heavy. Review it in **bounded slices** rather than as one 40+ file
wall of text.

The review question is not "do we like every future feature?" It is:

> Does this programme give future contributors one coherent architecture, explicit safety/privacy
> boundaries, small executable tasks, and honest evidence gates without changing runtime behavior?

## Merge gate

Before merge:

- [ ] PR is mergeable with current `main`.
- [ ] Tests workflow is green.
- [ ] Campaign preflight is green.
- [ ] CodeQL / dependency review / repository policy checks are green where applicable.
- [ ] ADR index generator check is green.
- [ ] MkDocs design navigation check is green.
- [ ] No runtime feature is falsely described as shipped.
- [ ] No human hardware task is advertised as agent-executable.
- [ ] Public QA is not described as research consent.
- [ ] No raw face/screen/audio upload is required by the default evaluation path.

## Slice A — architecture

Review:
- ADR-v2-135 shared camera perception;
- ADR-v2-136 PointerSink boundary;
- ADR-v2-137 face-switch intent;
- ADR-v2-138 hands-free composition/safety;
- ADR-v2-139 calibration/topology;
- ADR-v2-140 QA vs research evidence;
- ADR-v2-141 semantic grounding.

Check:
- one camera owner;
- derived signals rather than shared raw frames;
- pointer output stays behind platform boundary;
- face gestures emit intent rather than destructive actions;
- one global pause/fault model;
- stale calibration cannot silently remain trusted;
- semantic resolver may abstain;
- no screenshot/OCR/VLM dependency is smuggled into tier 1.

## Slice B — implementation contracts

Review:
- `design/specs/eye-*.md`;
- `AGENT_TASKS.md`;
- `TRACEABILITY.md`.

Check:
- one issue = one reviewable unit;
- exact blockers are named;
- pure logic is testable without camera hardware;
- optional dependencies stay lazy;
- platform-specific behavior is isolated;
- runtime and evidence tasks are separate.

## Slice C — safety and privacy

Review:
- `RISK_REGISTER.md`;
- `DATA_SHARING.md`;
- `GOVERNANCE.md`;
- `RESEARCH_PARTICIPANT_TEMPLATE.md`.

Check:
- independent stop/pause exists in the design;
- stale signal cannot repeat actions;
- wrong-target and abstention are distinguished;
- camera disabled means unopened/released;
- community QA does not request raw face/private desktop content;
- participant identity/consent records never belong in public GitHub.

## Slice D — evaluation and paper evidence

Review:
- `EVALUATION.md`;
- `METRICS.md`;
- `VALIDATION_MATRIX.md`;
- `PAPER_EVIDENCE.md`.

Check:
- CI/synthetic/hardware/human-study evidence are not conflated;
- person/session/trial/computer are separate units;
- A/B replication is explicit;
- failure results are preserved;
- false activations use an exposure-time denominator;
- paper human-data path has a pre-collection ethics/consent gate.

## Slice E — contributor experience

Review:
- `STATUS.md`;
- `BEGINNER_TESTING.md`;
- `CONTRIBUTING.md`;
- `VALIDATION_OPERATIONS.md`;
- issue templates.

Check:
- a beginner can tell READY from PLANNED;
- a no-code contributor is asked for one small pack, not the whole matrix;
- FAIL/BLOCKED still counts as useful evidence;
- hardware tasks never imply cloud-agent execution;
- task discovery will eventually integrate into the existing campaign finder instead of creating a
  parallel contribution system.

## Readiness after merge

Do **not** mass-add `help wanted` or `agent-ready` when #413 merges.

Run #493. It activates only Wave-1 issues whose exact design blockers are now on `main`.

Hardware slots #428–#440 remain PLANNED until the evaluator and relevant runtime/safety path are
actually merged.

## Non-goals of #413

The PR does not:
- ship Head-Pointer;
- ship face-switch control;
- claim dedicated eye-tracker support;
- enroll research participants;
- choose final product thresholds from synthetic traces;
- collect webcam recordings;
- make every open eye issue ready for an agent.

Those are later, individually reviewable changes.

## If review finds a policy disagreement

For an architectural disagreement:
1. identify the ADR/spec;
2. resolve the decision there;
3. update dependent issue acceptance criteria;
4. do not silently let an implementation task choose a competing architecture later.

For a wording/detail issue that does not change a decision, fix the document directly in #413.
