# Grounded Interaction Kernel contract — fit/gap against the code on `main`

**Date:** 2026-11-05  
**Status:** Research memo (R0, documentation only). No code changed, nothing accepted, nothing decided.  
**Baseline:** `main` at `a241a77b` (inspected 2026-11-05)  
**Decision record under study:** [ADR-025](../adr/adr-025-grounded-interaction-kernel.md), status **Proposed (2026-09-23)** and unchanged by this memo  
**Companion research page:** [Grounded Interaction Kernel research architecture](../../docs/research/interaction-kernel.md)  
**Governing direction:** [ADR-030](../adr/adr-030-agent-era-direction.md) (breadth freeze)  
**Related host-object requirements:** [XR decisions](../xr/DECISIONS.md) D6 and [XR architecture](../xr/ARCHITECTURE.md) (intent-proposal paragraph, line 77)

## Question

ADR-025 proposes a six-type kernel contract (`Observation`, `GroundedTarget`, `IntentHypothesis`,
`AuthorityContext`, `ActionProposal`, `ActionOutcome`) in a package `src/yazses/interaction/`.
That package does not exist. Before anyone decides whether to accept, amend or defer the ADR, this
memo answers a narrower and checkable question: **for eight properties a host-owned object
("colour this object") would need, which already exist in the code under other names, and which
are genuinely absent?**

It is a paper analysis of the code. It is not a prototype, and it does not exercise ADR-025's own
accept/reject criteria (those require a prototype slice; see "Options for the owner").

## Short finding

* Two of ADR-025's six concepts exist today under other names, and are better specified than the
  ADR assumes: `Observation` and `GroundedTarget` correspond to `TargetSnapshot`,
  `SemanticCandidate` and the tri-state `GroundingResult` in `src/yazses/grounding/contracts.py`.
  Freshness gating, an ambiguity gate and typed abstention reasons already exist and have five
  `tests/test_grounding_*` files.
* A consequence-times-confidence policy also already exists, which ADR-025 does not mention:
  `Consequence` and `Decision` in `src/yazses/activation/confirm.py`. It has two consequence
  values and three decisions, not ADR-025's five and five.
* Four things are absent for a host-owned object: an `ActionProposal` that binds target, verb,
  arguments and provenance; an `AuthorityContext` (scope, consent, expiry); an inverse or undo
  record for non-text changes; and a postcondition check after execution. A fifth, issuer and
  host state revision on the object identity, can be added to an existing type.
* One name clash must be settled before any implementation: `ActionOutcome` already exists in
  `src/yazses/facegesture/actions.py` with a different meaning.

## Fit/gap table

Gap class is one of **extension field on an existing type** (an additive, defaulted field or enum
member) or **new type**. Line numbers refer to the baseline above.

| # | Property | What exists (file:line) | Gap | Gap class |
|---|---|---|---|---|
| 1 | Host-owned object IDs | `SemanticCandidate.entity_id` and `role`, `actions`, `captured_at_s` (`grounding/contracts.py:280`); `SemanticSourceKind.APPLICATION` for "an application's own context provider" (`:265`); `SemanticSource` read-only protocol (`:335`). The docstring promises an ID is stable only "for the snapshot that produced it". | No issuer or session on the ID, so an app-issued ID and an AT-SPI-derived one look alike except for `source`. No scope on `actions` (a verb string, not a permission). No identity that survives a snapshot. XR D6 and ARCHITECTURE.md:77 already require "app-issued, session-scoped, fresh, resolvable, and have the required permission". | Extension field on `SemanticCandidate` (`issuer`, `session_id`), defaulted `None` so existing adapters are unchanged. See hazard H1. |
| 2 | State freshness | `ResolutionPolicy.max_target_age_s` and `max_candidate_skew_s` (`grounding/resolver.py:187`); `_target_failure` (`:504`) and `_reject` (`:609`); `UnresolvedReason.TARGET_STALE` and `SEMANTIC_ALL_STALE` (`grounding/contracts.py:433`); `CoordinateSpace.version` as an invalidation counter for geometry only (`:113`). | Freshness is time-only. Nothing says "the host object changed since I observed it" (a host state revision). Nothing re-checks at execution time, only at grounding time. `CoordinateSpace.version` covers layout, not object state. | Extension field (`host_revision` on `SemanticCandidate`); the execution-time re-check is new logic that belongs with the new proposal type (row 3). |
| 3 | Observation / proposal / action separation | Observation: `TargetSnapshot` (`:227`) and `SemanticCandidate` (`:280`). Interpretation: `IntentHint` (`:361`), whose `verb` the resolver deliberately ignores. Planning: `ToolCall` (tool, argument, score) in `agent/plan.py:27`. The resolver module states grounding "does not decide actions". | No type binds target + verb + arguments + provenance + the observed revision into the exact side effect under consideration. `ToolCall` carries a tool name and a string, with no target. | New type (`ActionProposal`). `Observation` needs no new type unless a non-spatial observation (a transcript) must travel with it. |
| 4 | Authorisation | `RiskAssessment` with string levels `safe`, `caution`, `dangerous` (`cmdsafety/classify.py:45`); `ConfirmGate` (`:63`); `Consequence` (REVERSIBLE or IRREVERSIBLE) and `decide(confidence, consequence)` (`activation/confirm.py:57`, `:127`); `ToolSpec.writes` and `needs_confirm` (`agent/plan.py:17`, `:74`). | Four unrelated vocabularies for "how bad is a wrong action". None is ADR-025's `OBSERVE / REVERSIBLE / EXTERNAL / DESTRUCTIVE / PHYSICAL`. There is no authority object: no scope ("this object only"), no consent record, no expiry, no statement of who granted it. | New type (`AuthorityContext`); the consequence vocabulary is an extension of `Consequence` (more members) but see hazard H2. |
| 5 | Ambiguity | `GroundingOutcome.AMBIGUOUS` with at least two `alternatives`, enforced in `GroundingResult.__post_init__` (`:480`); the gate `TargetResolver._indistinguishable` (`grounding/resolver.py:766`); candidate confidence and freshness deliberately excluded from separating a pair. | Ambiguity is over the **target** only. There is no representation of several action interpretations of one target ("colour" as fill, outline or theme). | New type (`IntentHypothesis`), or defer: the target half is done. |
| 6 | Abstention | `GroundingOutcome.UNRESOLVED` and the closed `UnresolvedReason` set (`grounding/contracts.py:433`); `Decision.REJECT` (`Decision` at `activation/confirm.py:64`). | `Decision` has ACT / CONFIRM / REJECT, ADR-025 wants execute / confirm / clarify / abstain / fall back. `UnresolvedReason` has no host-object causes (unknown issuer, revision mismatch, permission denied). | Extension (enum members). See hazard H3. |
| 7 | Reversible changes | `InjectionTimeline`, `UndoOp(backspaces, insert)` (`timeline/history.py:13`, `undo` at `:101`): text-injection deltas only. `activation/confirm.py` lists `undo` among REVERSIBLE actions, meaning the focused app's own undo stack. | No record of "the prior value of the property I changed" for a non-text object, and no contract by which a host says "I can revert this". | New type (an inverse record on the proposal or outcome), and a host capability the app must offer. |
| 8 | Outcome verification | `ActionOutcome(action, result, reason, at_s)` with DONE / REFUSED / NOOP (`facegesture/actions.py:85`), which records what the actuator reported. `SemanticCandidate.checked` (`grounding/contracts.py:280`) is a precedent for reading one state value back. | No postcondition, no verification method, no re-observation after execution. "The executor returned" is the only success signal. Candidates expose only `label` and `checked`, not a general property read-back. | New type (verified outcome); read-back is an extension field (`properties`) plus a second `SemanticSource.snapshot` call. |

### Hazards found while reading, for whoever implements any of this

* **H1 – the candidate tiebreak lists fields by hand.** `_identity_key` in `grounding/resolver.py:321`
  enumerates `SemanticCandidate` fields explicitly to make ordering independent of tree-walk order.
  A new field (issuer, revision) does not enter that key unless someone adds it, and two candidates
  differing only in the new field would again sort by input order. De-duplication
  (`dict.fromkeys`, `:549`) uses dataclass equality, so it would pick up new fields automatically,
  which is a different behaviour from the tiebreak. Tests should cover both.
* **H2 – four vocabularies, one concept.** Adding a fifth (ADR-025's) without collapsing the others
  would repeat the failure ADR-025 names as its main risk: "the kernel becomes a new umbrella" that
  increases independent paths. `activation/confirm.py` pins every dispatcher action in a test
  (`tests/test_activation_intent.py`, per its docstring), so widening `Consequence` has a test-side cost.
* **H3 – `UnresolvedReason` families are derived from the member name prefix** (`TARGET_`,
  `SEMANTIC_`; `grounding/contracts.py:433`). A host-object cause named any other way would belong
  to neither family property, which the evaluation plan reports separately.

## Worked scenario (synthetic)

All values are invented. This is a thought experiment on a toy scene host, not a feature, and uses
only type names present on `main` except where a gap is marked **[GAP n]** (row numbers refer to the
table).

1. **Observation.** A toy host application "scene" shows three shapes. The user looks at the middle
   one and says "colour this blue". A gaze `TargetSnapshot(source=TargetSource.GAZE,
   timestamp_s=100.0, confidence=0.8, space=CoordinateSpace("host-canvas", 3), point=Point(120, 80))`
   is recorded. A `SemanticCandidate(source=SemanticSourceKind.APPLICATION, entity_id="obj-17",
   role="shape", captured_at_s=100.0, confidence=0.9, bounds=..., label="Cube",
   actions=("set_colour",))` is returned by the host's `SemanticSource`. **[GAP 1]** nothing records
   that `obj-17` was issued by the scene host for this session. **[GAP 2]** nothing records the
   host's state revision at capture.
2. **Candidate.** `TargetResolver.resolve(target, candidates, now_s=100.1, hint=IntentHint(verb="colour"))`
   returns `GroundingResult` with outcome `GROUNDED` and `obj-17` as `candidate`. The verb "colour"
   is carried in the hint but not used by the resolver (by design). **[GAP 5]** "colour" could mean
   fill or outline; there is no place to hold both readings.
3. **Proposal.** The system needs one object: "set `obj-17` fill to blue, observed at host revision
   N, requested by this utterance". **[GAP 3]** no such type exists; the nearest, `ToolCall`, has
   no target.
4. **Authority check.** Colour change is local and presumably reversible, so the policy would ask:
   is this action in scope, and has the user permitted the host to be driven at all?
   `classify_consequence` (`activation/confirm.py:110`) would return IRREVERSIBLE for an unknown
   action name such as `set_colour`, because unknown defaults to the safe direction, and `decide`
   would then return CONFIRM at any confidence. **[GAP 4]** the code cannot say "reversible, because
   the host offers revert", and has no scope or consent object. Nothing here is wrong; it
   shows the existing policy is conservative and cannot express the distinction.
5. **Action.** Out of scope for a memo. Nothing in `src/yazses` calls a host-object API, and this
   memo proposes none.
6. **Verification.** After execution the system would re-read `obj-17` and compare its fill to
   blue. **[GAP 8]** the candidate has no property to compare, and `ActionOutcome` (facegesture)
   would only record that the actuator returned.
7. **Undo.** If the user says "undo", the prior fill must be known. **[GAP 7]** `UndoOp` undoes text
   injection only.

### Failure rows the existing contract already handles

Run on `main` in a scratch script (not committed) with a synthetic canvas, the existing types
produced these results:

| Situation | Result |
|---|---|
| Gaze point inside one candidate's bounds | `GROUNDED` |
| Two candidates with identical bounds | `AMBIGUOUS` |
| Target 1.0 s older than `now_s` (budget 0.5 s) | `UNRESOLVED`, `TARGET_STALE` |
| Candidate captured 2 s after the target | `UNRESOLVED`, `SEMANTIC_ALL_STALE` |
| Candidate in `CoordinateSpace` version 4, target in version 3 | `UNRESOLVED`, `SEMANTIC_SPACE_MISMATCH` |
| Two candidates with the same `entity_id`, same bounds, same fields | compare equal; the contract cannot tell "the same object" from "the object after the host changed it" (gap 2) |

This establishes only that the current resolver behaves as its own tests say on a synthetic layout.
It says nothing about any real application or user.

## Proposal for the `ActionOutcome` name clash (not applied)

`ActionOutcome` is already defined in `src/yazses/facegesture/actions.py:85` (22 references, all in
that module and `tests/test_facegesture_actions.py`). ADR-025 and the research page use the same
name for a different thing: a verified postcondition. Two options, neither applied:

1. **Rename the existing one** to `SwitchOutcome`. It sits beside the existing `SwitchOutcomeLog`
   (`:105`), so the naming becomes consistent. Cost: a rename touching one source module and one
   test file, plus anything an in-flight branch holds. Benefit: the ADR keeps its vocabulary.
2. **Name the kernel type differently** when and if the ADR is accepted (for example
   `VerifiedOutcome`), and amend the ADR text then. Cost: an ADR amendment. Benefit: no source
   change at all now.

Option 2 changes nothing today and is the one a docs-only freeze permits. Option 1 is a refactor
that the freeze's allow-list ("bug fixes ... removal; tests ... documentation") does not clearly
cover, so it would need the owner's call.

## What the freeze allows

ADR-030 section 3 freezes breadth until the first substantive issue from a non-contributor. It
allows documentation, tests, CI, bug fixes and removal. A proposal outside the pillars is "written
down as a *Proposed* ADR or an `evergreen:research` issue and stops there". Lifting the freeze
requires an amendment to ADR-030 with the triggering evidence; the 2026-11-01 amendment named one
exception (biosignal) and left the freeze in place.

| Activity | Allowed? | Basis |
|---|---|---|
| This memo (docs-only R0 research) | Yes | Same status as `design/xr/ROADMAP.md` "Phase R0: research and decision (allowed during freeze)" |
| Keeping ADR-025 at *Proposed* | Yes | ADR-030 section 3 |
| Creating `src/yazses/interaction/` | **No** | A new package is breadth; no amendment exists |
| Adding fields to `SemanticCandidate` or members to `Consequence`/`UnresolvedReason` | **No** (as feature work) | Would be new capability outside the four pillars |
| A second kernel, a cloud twin, a personal or biometric replica, live control, an SDK integration | **No** | Out of scope here and not approved by ADR-025 itself (its own "does not decide" list) |
| Renaming `ActionOutcome` | Unclear | Refactor, not clearly in the allow-list; owner's call |

Issue #700 (open, scoped to `examples/hci-hf-lab/eval`) is a pure local replay harness. This memo
defines no fixture schema. Whatever a host-object scenario would need to be replayed belongs in
the existing `examples/hci-hf-lab/fixtures.schema.json` lineage owned by #699 (closed) and #700,
and should be proposed there rather than here.

## Options for the owner

Each is a choice for the owner. This memo does not recommend one, does not recommend lifting the
freeze, and does not treat ADR-025 as accepted.

| Option | Evidence for | Evidence against / cost |
|---|---|---|
| **Accept** ADR-025 as written | The need it names is real: four consequence vocabularies and two outcome-like types exist today (rows 4, 8). XR D6 already requires app-issued, fresh, permissioned IDs. The ADR's own "main failure mode" (a new umbrella) is the risk if the existing paths are not collapsed. | Acceptance authorises a package the freeze prevents building. Two of six types already exist under other names, so the ADR as written understates existing work and would duplicate `GroundingResult`. The ADR's own accept/reject tests need a prototype that has not been built. No non-contributor demand is evidenced. |
| **Amend** ADR-025 (still *Proposed*, or accepted later) | This memo's table gives concrete amendments: map `Observation`/`GroundedTarget` onto the grounding types; build on `Consequence`/`decide` rather than add a parallel policy; settle the `ActionOutcome` name; reduce the new types to the four that are absent. | An amendment edits an ADR text, which this memo was told not to touch. Amending without a prototype is still a paper exercise. |
| **Defer** (leave *Proposed*, revisit on evidence) | Consistent with ADR-030 section 3: no substantive non-contributor issue exists, and no issue for a "digital twin" or host-object use exists. Nothing in this memo was run on hardware or with real users. `design/xr/ROADMAP.md` itself says to stop after R0 if need is not shown. | The vocabulary drift (H2) and the name clash persist and can accumulate more instances while the decision waits. |

## What was and was not checked

* Checked: the quoted types, signatures and line numbers were read on `main` at `a241a77b`;
  the table of resolver outcomes above was produced by running the existing resolver on a synthetic
  layout.
* **Not hardware-tested.** No camera, gaze tracker, headset, host application or device was used.
  The scenario is synthetic and no host-object API exists in the code.
* **No non-contributor demand evidence exists** for a host-object or digital-twin interaction, and
  this memo does not create any. Issue search for "digital twin" returned no matching issue on
  2026-11-05.
* Not checked: ADR-021 and ADR-022 were not re-read for this memo beyond ADR-025's references to
  them; neither was any claim here derived from them.
* The default thresholds in `ResolutionPolicy` are, by the module's own statement, not measured;
  nothing here validates them.
