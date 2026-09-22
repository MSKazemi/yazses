# Spec: Implicit Gaze Calibration — Click Association, Held-Out Promotion and Topology Safety

| Field | Value |
|---|---|
| **ID** | spec-eye-implicit-calibration |
| **Status** | Proposed |
| **Date** | 2026-09-22 |
| **Modules** | `src/yazses/gaze/implicit.py`, store/runtime click observer |
| **Related** | ADR-v2-010, ADR-v2-139, ADR-014 |
| **Issues** | #397–#399 + topology/HiDPI task |

## Goal

Finish the runtime half of implicit gaze calibration while guaranteeing that passive learning cannot
silently replace a better explicit calibration or survive an incompatible desktop topology.

## Existing core

`gaze/implicit.py` already provides the incremental estimator and `refined_if_better` held-out
comparison.

This spec covers missing runtime acquisition, persistence, topology context and promotion.

## Non-goals

- no raw click text/window content;
- no screenshots;
- no frame storage;
- no cloud learning;
- no automatic caret targeting;
- no unconditional online replacement of the baseline.

## Sample association

A candidate sample is:

```text
(timestamped gaze features, confidence)
       +
(timestamped user pointer click x/y)
       ->
calibration observation
```

The click observer is platform-neutral at the estimator boundary.

Association rules:
- choose a gaze observation within a documented look-back/association window;
- reject when no fresh observation exists;
- reject below confidence threshold;
- reject implausible residual/outlier per existing core policy;
- record only derived numeric observation needed by estimator.

The exact latency offset should be configurable/research-measurable rather than hard-coded forever.

## Sample buffers

Separate:
- training/update samples/state;
- held-out validation samples.

A sample used to fit a candidate is not simultaneously evidence that the candidate improved.

Use bounded state/history consistent with existing incremental design and privacy goals.

## Baseline and candidate

- **baseline** = explicit calibration currently accepted for this calibration context;
- **candidate** = implicit refinement.

Candidate may become active only when `refined_if_better`/equivalent held-out gate wins by the
defined margin/sample requirement.

## Persistence

Calibration artifact includes:
- map coefficients;
- source: explicit / implicitly refined;
- version;
- timestamp;
- ADR-v2-139 context fingerprint.

Write atomically.

A failed candidate leaves the prior artifact exactly valid.

Keep enough metadata to report/rollback the previous accepted map if rollback is a supported command.

## Context/topology

Before applying stored calibration:
- compare current display/camera context to saved fingerprint;
- incompatible context -> mark stale, do not route with it;
- topology change during session -> suspend gaze routing until refreshed/revalidated.

Tests cover:
- single monitor 1.0 scale;
- 2x/HiDPI;
- negative-origin second monitor;
- changed arrangement/resolution;
- changed camera identifier.

## User control

Implicit refinement is opt-in.

Status reports:
- baseline source;
- candidate sample count;
- last evaluation result;
- stale/valid reason;
- no raw personal data.

A user can disable refinement without deleting explicit calibration.

## Acceptance criteria

- Low confidence click pair is rejected.
- Stale gaze sample is rejected.
- Training sample does not leak into holdout verdict.
- Worse candidate cannot replace baseline.
- Better candidate promotes atomically.
- Persistence failure leaves baseline valid.
- Incompatible topology refuses stored map.
- Same compatible topology reuses map.
- Report/export contains derived metrics only.

## Tests

- existing `tests/test_gaze_implicit.py`;
- fake click observer;
- fake clock/ring buffer;
- atomic store failure;
- topology fixtures;
- rollback;
- privacy schema golden test.

## Field evaluation

Report:
- explicit baseline error;
- candidate held-out error;
- sample count/time;
- drift over session;
- dock/undock/camera change outcome.

No promotion to recommended implicit calibration without longitudinal field evidence.
