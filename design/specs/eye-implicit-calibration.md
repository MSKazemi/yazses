# Spec: Implicit Gaze Calibration — Click Association, Held-Out Promotion and Topology Safety

| Field | Value |
|---|---|
| **ID** | spec-eye-implicit-calibration |
| **Status** | Proposed |
| **Date** | 2026-09-22 |
| **Modules** | `src/yazses/gaze/implicit.py`, store/runtime click observer |
| **Related** | ADR-v2-010, ADR-v2-149, ADR-014 |
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

As built (#398) the verdict is the pure function `gaze.refine.decide_promotion(baseline,
candidate, holdout, *, train_samples, policy)`: no I/O, clock or state, arguments unmodified.
It returns `insufficient_data` below `min_train_samples`/`min_holdout_samples`, otherwise
`applied` only when both held-out mean errors are finite, the candidate's is strictly lower,
and `baseline − candidate ≥ min_improvement_px` (policy-enforced `> 0`); anything else —
including a baseline compared with itself — is `kept_baseline`. `applied` is the verdict, not
the deed: the refiner still confirms the context and writes atomically, reporting
`stale_context` or `persist_failed` if either fails. The split is the pure
`gaze.refine.routes_to_holdout(index, holdout_every)`, by position only.

## Persistence

Calibration artifact includes:
- map coefficients;
- source: explicit / implicitly refined;
- version;
- timestamp;
- ADR-v2-149 context fingerprint.

Write atomically.

A failed candidate leaves the prior artifact exactly valid.

Keep enough metadata to report/rollback the previous accepted map if rollback is a supported command.

As built (#398): one level of history, `gaze_calibration.previous.json`, byte-identical to
the artifact the last promotion replaced; `yazses gaze rollback` restores it byte for byte;
a new explicit calibration removes it. The `version` field is read on load: absent = 1;
present but not a positive integer = damaged (STALE, as #415). A file from a newer schema
still routes (its map and `space` are checked on their own) but `promote_refinement`
refuses to re-encode it, since that would drop fields this build cannot read. The stored
key set is pinned by a golden test (`tests/test_gaze_calibration_promotion_contract.py`):
map coefficients, source, version, space, timestamp, context + fingerprint and, for an
implicit map, four scalar evidence numbers — no samples, clicks, frames or screen content.

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

## Backends

### Windows

`platform/windows/click_observer.py` (#607) installs a `WH_MOUSE_LL` low-level mouse hook on
a dedicated thread with its own message loop, the shape `platform/windows/hotkey.py` already
uses. `WM_LBUTTONDOWN`, `WM_RBUTTONDOWN` and `WM_MBUTTONDOWN` each become one
`ClickEvent(time.monotonic(), x, y)`; wheel, move, button-up and X-button messages produce
nothing. The event names no button, no window and no text — the value has no field for them —
and `MSLLHOOKSTRUCT.pt` is read as the hook reports it (primary-origin, negative left/above;
the DPI factor belongs to the still-missing Windows topology provider, see the module
docstring). The hook procedure only enqueues and returns `CallNextHookEx` — never `1` — because
`LowLevelHooksTimeout` (300 ms default) silently removes a slow hook; the callback runs on a
second thread. `start()` raises `ClickObserverError` naming `GetLastError` when the hook is
refused. Hermetic tests: `tests/test_click_observer_windows.py`. **No real-Windows evidence
yet**: a hook has not been installed on a Windows desktop by this code; that smoke report is
still owed before the refiner is described as working there.
