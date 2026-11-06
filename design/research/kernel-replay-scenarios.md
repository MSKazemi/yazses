# Host-object replay scenarios for the existing grounding contract

- **Date:** 2026-11-06
- **Status:** Research draft, documentation only. Review pending. No code changed, no fixture committed, no schema added, nothing accepted.
- **Baseline:** `main` at `8a72bbc6` (every `file:line` below refers to that commit)
- **Decision record under study:** [ADR-025](../adr/adr-025-grounded-interaction-kernel.md), status **Proposed (2026-09-23)**. This note does not change that status.
- **Builds on:** [Kernel contract fit/gap memo](kernel-contract-fit.md) (its gap numbers 1-8 are used below as **[GAP n]**)
- **Issue context:** [#700](https://github.com/MSKazemi/yazses/issues/700) (HCI-HF-007, pure replay evaluation, open on 2026-11-06, scoped to `examples/hci-hf-lab/eval`)
- **Governing direction:** [ADR-030](../adr/adr-030-agent-era-direction.md) section 3 (breadth freeze)

## Labels that apply to every scenario

* **Synthetic.** Every value is invented: a toy "scene" host with one shape, `obj-17`, in an
  invented coordinate space `host-canvas`. No real application, user, recording or person.
* **Linux-only reading, no hardware.** The outcomes come from reading pure Python modules that do
  not touch the platform. No camera, gaze tracker, headset, host application or device was used.
* **Not executed tonight.** The outcomes below were **derived by reading the code**, not by
  running it. The acceptance bar for this note is a run of the real resolver on the appendix
  trace. Until that run happens, every "Existing-contract outcome" cell is a prediction. The run
  commands are in the "How to confirm" section.

## Question

The fit/gap memo found that the grounding contract already handles time freshness, layout
invalidation and target ambiguity. It also found that a host-owned object lacks a state revision,
an authority object, an inverse record and a postcondition check. This note asks a narrower,
replayable question:

> For at most six synthetic host-object situations, what does the **existing** contract return
> today, and where does that answer differ from what a host-object kernel would need?

The note expresses each situation in the **existing** grounding trace format
(`TRACE_SCHEMA_VERSION = "1.0"`, `src/yazses/grounding/trace.py:72`). The real
`TargetResolver` can replay that format through `scripts/replay_grounding_trace.py --trace`
without any new code. The note adds no fields to that format or to
`examples/hci-hf-lab/fixtures.schema.json`.

## Shared setup

Policy: the `ResolutionPolicy` defaults (`src/yazses/grounding/resolver.py:187`). These
defaults are not measured, as the module's own docstring says. The relevant values are
`max_target_age_s = 0.5` (`:207`), `max_candidate_skew_s = 0.5` (`:211`),
`min_target_confidence = 0.5` and `tie_distance_px = 4.0` (`:228`).

Every scenario has the same target: a gaze `TargetSnapshot` at `timestamp_s = 100.0`,
`confidence = 0.8`, `space = host-canvas v3`, `point = (120, 80)`. Resolution happens at
`now_s = 100.1`, so the target is 0.1 s old and passes `_target_failure`
(`resolver.py:504`).

Unless a scenario says otherwise, `obj-17` is an `APPLICATION` candidate with role `shape`,
`bounds = (100, 60, 40, 40)` in `host-canvas v3`, `confidence = 0.9`, label `Cube` and actions
`["set_colour"]`. The point (120, 80) lies inside those bounds.

## How the outcome vocabularies line up

Three vocabularies appear below. This table maps them and invents no new one.

| Resolver (`GroundingOutcome`, `contracts.py:471`) | `activation/confirm.py` `Decision` (`:64`) | `examples/hci-hf-lab` `decision` (`fixtures.schema.json` `$defs.decision`) |
|---|---|---|
| `GROUNDED` ("resolved") | `ACT` or `CONFIRM`, decided separately | `accept` or `ask_confirmation` |
| `AMBIGUOUS` | none (a resolver result, not a decision) | `abstain` (the lab resolver abstains on an ambiguous target, `examples/hci-hf-lab/resolver.js:35`) |
| `UNRESOLVED` | none | `abstain` |
| none | `REJECT` (confidence below `DEFAULT_REJECT_FLOOR = 0.50`, `confirm.py:54`) | `abstain` |

The hci-lab `stop` decision (emergency stop) has no counterpart in either Python module. None of
the scenarios uses it.

The resolver and `decide` are **not wired together** anywhere in `src/yazses` today. Scenarios 5
and 6 show their composition as a thought experiment: each function's output is predicted
separately, and the arrow between them is hypothetical.

## The six scenarios

The *expected_entity_id* column holds the ground truth written into the appendix trace. It records
what a host-object kernel **should** do, so `null` means abstaining is correct. A replay therefore
scores any scenario where the existing contract grounds but should not as `grounded_wrong`, which
makes the gap visible as a number.

| # | Property probed | Situation | Existing-contract outcome (predicted from code) | Why (code path) | expected_entity_id | Gap the outcome exposes |
|---|---|---|---|---|---|---|
| S1 | State freshness (time) | The host's snapshot of `obj-17` was captured at 98.0, 2.0 s before the gaze target. | `UNRESOLVED`, `SEMANTIC_ALL_STALE`. hci-lab: `abstain`. | The skew of 2.0 s exceeds 0.5 s, so `_reject` returns `STALE` (`resolver.py:645`). That is the only rejection cause, so `_semantic_failure` reports the specific reason (`:520`). | `null` | None. The existing contract already handles this case (it repeats the memo's failure-row table in replayable form). |
| S2 | Revision mismatch (layout) | The host re-laid out the canvas, so `obj-17` is reported in `host-canvas v4` while the target is in v3. | `UNRESOLVED`, `SEMANTIC_SPACE_MISMATCH`. hci-lab: `abstain`. | `candidate.space != target.space` (`resolver.py:643`). `CoordinateSpace` is a frozen value of `(name, version)` (`contracts.py:113`). | `null` | None for **layout**. `CoordinateSpace.version` invalidates geometry only (memo row 2). |
| S3 | Revision mismatch (object state) | The host reports `obj-17` twice, at 100.0 and at 100.2. Between the two reports its fill changed from red to blue. Every field the contract carries is the same; only `captured_at_s` differs. | `GROUNDED` on `obj-17` (the 100.0 reading), `resolution_confidence = 0.8`. hci-lab: `accept` or `ask_confirmation` (see S5). | `_one_per_entity` treats the two as readings of one control and keeps the one closest in time to the target (`resolver.py:584`). Nothing in `SemanticCandidate` (`contracts.py:280`) records the fill or a host revision. | `null` (a kernel should re-validate before acting) | **[GAP 2]** No host state revision exists. The contract cannot tell "the same object" from "the object after the host changed it", so the replay scores this case `grounded_wrong`. |
| S4 | Object identity | The host moved `obj-17` by 4 px between the two reports. Reading A has bounds `(100, 60, 40, 40)` at 100.0 and reading B has `(104, 60, 40, 40)` at 100.2. Both contain the point. | `AMBIGUOUS` between the two `obj-17` readings, with shared evidence `INSIDE_TARGET_REGION`. hci-lab: `abstain`. | The bounds differ, so `_one_per_entity` keeps both, as its docstring says it must ("a source defect and stays visible as an ambiguity"). Both are in the same tier (APPLICATION, containment 2) with equal area, and both distances are 0. `_indistinguishable` therefore returns `True` (`resolver.py:766`). | `null` | **[GAP 1]** The abstention is correct, but the reason ("one object at two positions") cannot be stated. `UnresolvedReason` and the ambiguity type have no host-object cause (memo hazard H3). |
| S5 | Authority | "Colour this blue": a single-candidate scene, as in S3 but with only the 100.0 reading, and hint `IntentHint(verb="colour")`. | Resolver: `GROUNDED` on `obj-17`, `resolution_confidence = min(0.8, 0.9) = 0.8` (`resolver.py:479`). The resolver ignores the verb (`contracts.py:361`). Then, hypothetically, `classify_consequence("set_colour")` returns `IRREVERSIBLE`, because the name is not in the allow-list (`confirm.py:81`, `:110`), and `decide(0.8, IRREVERSIBLE)` returns `CONFIRM` (`confirm.py:127`; 0.8 ≥ floor 0.50, and IRREVERSIBLE always confirms). hci-lab: `ask_confirmation`. | Unknown actions default to the safe direction by design. | `obj-17` | **[GAP 4]** The outcome is conservative, which is safe. The contract cannot express "reversible because the host offers revert", "only this object" (scope), consent or expiry. |
| S6 | Outcome check and undo | After "colour this blue" was confirmed and (hypothetically) executed, the host re-reports `obj-17` at 100.05 with the new fill. The user then says "undo". | Resolver: `GROUNDED` on `obj-17`, and the result is field-for-field the one S5 produced, except for `captured_at_s`. Hypothetically, `classify_consequence("undo")` returns `REVERSIBLE` (in the allow-list at `confirm.py:81`), and `decide(0.8, REVERSIBLE)` returns `CONFIRM`, because 0.8 < `DEFAULT_CONFIRM_THRESHOLD = 0.90` (`confirm.py:53`). hci-lab: `ask_confirmation`. | The re-observation carries no property, so it cannot be compared with "blue". `undo` in `confirm.py` means the focused application's own undo stack, and `UndoOp` (`timeline/history.py:13`) reverts text injection only. | `obj-17` | **[GAP 8]** No postcondition can be checked: the before and after observations are indistinguishable. **[GAP 7]** No prior value is recorded, so nothing in YazSes can revert the fill. Whether "undo" works depends entirely on the host. |

### What the six scenarios establish, and what they do not

* S1 and S2 restate, in replayable form, two rows the memo already produced by running a scratch
  script. They are included so that one trace covers both the cases the contract already handles
  and the cases it cannot handle.
* S3 is the clearest case: the existing contract **grounds confidently** in a situation where a
  host-object kernel would need to re-validate. It does not mislead the user today, because nothing
  in `src/yazses` acts on a host object. It is a gap only for a future that ADR-025 proposes and
  ADR-030 freezes.
* S5 and S6 show that the existing consequence policy errs toward confirming. Nothing here argues
  for loosening it.
* The scenarios say **nothing** about any real application, any real accessibility tree, any
  user, or any threshold value. The policy defaults are unmeasured, and a synthetic trace cannot
  license them.

## What this note deliberately does not do

* It adds **no fixture schema** and no field to the grounding trace or the hci-lab schema. If #700
  wants host-object cases in its harness, the decision belongs in that issue's
  `examples/hci-hf-lab/fixtures.schema.json` lineage, as the memo already says.
* It commits **no fixture file**. The appendix trace lives only in this note so that it cannot
  enter `tests/fixtures/grounding_replay_report.json` or the CI drift gate by accident.
* It changes **no `src/` code**, adds no field to `SemanticCandidate`, and adds no member to
  `UnresolvedReason` or `Consequence`. The ADR-030 freeze table in the memo still applies.
* It **does not move ADR-025** from Proposed, and it does not recommend Accept, Amend or Defer.
  That remains the owner's choice, using the memo's options table.
* It proposes no ThinkGear, EEG, XR or digital-twin runtime.

## How to confirm (the step this note is waiting for)

Save the appendix JSON to a scratch path outside the repository, for example
`$TMPDIR/kernel-replay-scenarios.json`. Then run these commands from the repository root:

```sh
uv run python scripts/replay_grounding_trace.py --trace "$TMPDIR/kernel-replay-scenarios.json"
uv run python -m pytest tests/test_adr_index_is_current.py -q
```

Expected from the first command, per case under `semantic_grounding`:
S1 unresolved/`semantic_all_stale`, S2 unresolved/`semantic_space_mismatch`, S3
`grounded_wrong` (ground truth `null`, resolver grounded `obj-17`), S4 ambiguous, S5 and S6
`grounded_correct`. Under `window_only`, every case is expected to be unresolved with
`semantic_no_candidates`, because no candidate has source `window`
(`src/yazses/grounding/replay.py:184`).

For the `decide` half of S5 and S6, a one-line check:

```sh
uv run python -c "from yazses.activation.confirm import classify_consequence as c, decide as d; print(d(0.8, c('set_colour')), d(0.8, c('undo')))"
```

Expected output: `Decision.CONFIRM Decision.CONFIRM`.

If any observed outcome differs from a prediction, **replace the cell with the observed value**
and record the run's commit. Do not adjust the trace to match the prediction.

## Appendix: the synthetic trace (grounding trace schema 1.0, existing format)

```json
{
  "schema_version": "1.0",
  "trace_id": "kernel-replay-scenarios",
  "study_mode": "synthetic",
  "description": "Synthetic host-object scenarios S1-S6 from design/research/kernel-replay-scenarios.md. Invented toy scene; no real application or user.",
  "space": {"name": "host-canvas", "version": 3},
  "cases": [
    {
      "case_id": "s1-stale-host-snapshot",
      "description": "Host snapshot captured 2.0 s before the gaze target.",
      "now_s": 100.1,
      "target": {"source": "gaze", "timestamp_s": 100.0, "confidence": 0.8, "point": {"x": 120.0, "y": 80.0}},
      "candidates": [
        {"source": "application", "entity_id": "obj-17", "role": "shape", "captured_at_s": 98.0, "confidence": 0.9,
         "bounds": {"x": 100.0, "y": 60.0, "width": 40.0, "height": 40.0}, "label": "Cube", "actions": ["set_colour"]}
      ],
      "hint": null,
      "expected_entity_id": null
    },
    {
      "case_id": "s2-layout-revision-mismatch",
      "description": "Host re-laid out the canvas: candidate in host-canvas v4, target in v3.",
      "now_s": 100.1,
      "target": {"source": "gaze", "timestamp_s": 100.0, "confidence": 0.8, "point": {"x": 120.0, "y": 80.0}},
      "candidates": [
        {"source": "application", "entity_id": "obj-17", "role": "shape", "captured_at_s": 100.0, "confidence": 0.9,
         "space": {"name": "host-canvas", "version": 4},
         "bounds": {"x": 100.0, "y": 60.0, "width": 40.0, "height": 40.0}, "label": "Cube", "actions": ["set_colour"]}
      ],
      "hint": null,
      "expected_entity_id": null
    },
    {
      "case_id": "s3-state-revision-invisible",
      "description": "Two reports of obj-17; the fill changed between them but no carried field differs except captured_at_s.",
      "now_s": 100.1,
      "target": {"source": "gaze", "timestamp_s": 100.0, "confidence": 0.8, "point": {"x": 120.0, "y": 80.0}},
      "candidates": [
        {"source": "application", "entity_id": "obj-17", "role": "shape", "captured_at_s": 100.0, "confidence": 0.9,
         "bounds": {"x": 100.0, "y": 60.0, "width": 40.0, "height": 40.0}, "label": "Cube", "actions": ["set_colour"]},
        {"source": "application", "entity_id": "obj-17", "role": "shape", "captured_at_s": 100.2, "confidence": 0.9,
         "bounds": {"x": 100.0, "y": 60.0, "width": 40.0, "height": 40.0}, "label": "Cube", "actions": ["set_colour"]}
      ],
      "hint": null,
      "expected_entity_id": null
    },
    {
      "case_id": "s4-same-id-moved",
      "description": "Host moved obj-17 by 4 px between reports; both readings contain the point.",
      "now_s": 100.1,
      "target": {"source": "gaze", "timestamp_s": 100.0, "confidence": 0.8, "point": {"x": 120.0, "y": 80.0}},
      "candidates": [
        {"source": "application", "entity_id": "obj-17", "role": "shape", "captured_at_s": 100.0, "confidence": 0.9,
         "bounds": {"x": 100.0, "y": 60.0, "width": 40.0, "height": 40.0}, "label": "Cube", "actions": ["set_colour"]},
        {"source": "application", "entity_id": "obj-17", "role": "shape", "captured_at_s": 100.2, "confidence": 0.9,
         "bounds": {"x": 104.0, "y": 60.0, "width": 40.0, "height": 40.0}, "label": "Cube", "actions": ["set_colour"]}
      ],
      "hint": null,
      "expected_entity_id": null
    },
    {
      "case_id": "s5-authority-colour-this",
      "description": "'Colour this blue' on a single fresh candidate; the verb is carried but not used by the resolver.",
      "now_s": 100.1,
      "target": {"source": "gaze", "timestamp_s": 100.0, "confidence": 0.8, "point": {"x": 120.0, "y": 80.0}},
      "candidates": [
        {"source": "application", "entity_id": "obj-17", "role": "shape", "captured_at_s": 100.0, "confidence": 0.9,
         "bounds": {"x": 100.0, "y": 60.0, "width": 40.0, "height": 40.0}, "label": "Cube", "actions": ["set_colour"]}
      ],
      "hint": {"verb": "colour", "role": null, "label_tokens": []},
      "expected_entity_id": "obj-17"
    },
    {
      "case_id": "s6-outcome-check-after-change",
      "description": "Re-observation after the (hypothetical) colour change; indistinguishable from the pre-change observation.",
      "now_s": 100.1,
      "target": {"source": "gaze", "timestamp_s": 100.0, "confidence": 0.8, "point": {"x": 120.0, "y": 80.0}},
      "candidates": [
        {"source": "application", "entity_id": "obj-17", "role": "shape", "captured_at_s": 100.05, "confidence": 0.9,
         "bounds": {"x": 100.0, "y": 60.0, "width": 40.0, "height": 40.0}, "label": "Cube", "actions": ["set_colour"]}
      ],
      "hint": null,
      "expected_entity_id": "obj-17"
    }
  ]
}
```

## What was and was not checked

* **Read at `8a72bbc6`:** `src/yazses/grounding/contracts.py`, `resolver.py` and the case format
  in `trace.py`; `src/yazses/activation/confirm.py:53-143`; the `$defs.decision` and scenario
  shape of `examples/hci-hf-lab/fixtures.schema.json`; the memo `kernel-contract-fit.md`.
* **Checked on 2026-11-06 with `gh issue view 700` (read-only):** #700 is OPEN.
* **Not run:** the resolver, the replay script, `decide`, the trace validator and every test.
  Until the "How to confirm" commands are run, every outcome cell is a prediction from reading
  the code.
* **Not checked:** whether the trace validator accepts a target with no `window_id` (the
  committed fixtures always set one; `trace.py` reads it as optional). If the validator rejects
  the appendix, fix the trace and keep the reasoning the same.
