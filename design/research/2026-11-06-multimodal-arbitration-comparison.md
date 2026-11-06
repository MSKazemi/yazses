# Multimodal arbitration for hands-free input: what the code does today, and three policies to compare

**Date:** 2026-11-06 · **Baseline:** `main` at `1698395d` · **Issue:** [#815](https://github.com/MSKazemi/yazses/issues/815) (NEXT-A11Y-03), epic [#790](https://github.com/MSKazemi/yazses/issues/790)
**Status:** Research note (not a decision). ADR-030 freeze unchanged. No `src/` change, no new activation feature, no study authorised, no participant recruited.
**Siblings (not duplicated):** [#813](https://github.com/MSKazemi/yazses/issues/813) task inventory (`2026-11-05-handsfree-task-inventory-and-evidence-gaps.md`), [#816](https://github.com/MSKazemi/yazses/issues/816) stop and unintended activation (`2026-11-05-emergency-stop-and-unintended-activation-threat-model.md`), [#695](https://github.com/MSKazemi/yazses/issues/695) camera comparison protocol. Delivery stays under [#102](https://github.com/MSKazemi/yazses/issues/102) and [#692](https://github.com/MSKazemi/yazses/issues/692).

Tags on every statement: **[Verified-in-code]** read in this snapshot (file:line on `1698395d`); **[Verified-primary-source]** read at a cited primary page; **[Unknown]** not established. Everything here is a reading of source and docstrings. I ran no test, no camera, no desktop session, so there is **no** hardware, Wayland, macOS, Windows, medical or accessibility-outcome result in this note, and none is implied. Where behaviour is described it is what the code is written to do, on Linux-oriented code paths, read statically.

## 1. Question

How should an uncertain target, an old camera frame, an ambiguous spoken command, a switch press and a contradiction between modalities lead to safe abstention? [#815] This note (a) inventories how the repository already combines modalities, (b) lists conflict cases and what the code does for each, (c) compares at most three arbitration policies against the one-camera rule, and (d) lists open questions for a human study. It does not choose a policy.

## 2. Finding in one paragraph

There is **no general arbitration layer** in the code. [Verified-in-code] What exists is a set of narrow, separately owned rules: a window-level gaze route with a confidence floor, a deixis grammar that turns "this/that" into that window, a pure grounding resolver that abstains on stale or ambiguous input, a global fail-closed gate with epochs, and a recovery ladder that refuses a destructive action on an inferred stand-in. They meet only in two places (gaze plus voice for deixis, head pose plus face switch for select), and **no code path reads a gaze target and a head-pointer position together**. The grounding contract has a `HEAD_POINTER` provenance member that nothing in `src/` produces (section 3.7). The semantic grounder is not constructed by any production caller, so element-level gaze grounding does not run in the shipped daemon. Whether any arbitration policy helps a real user is **[Unknown]**.

## 3. Inventory: where modalities already meet (all [Verified-in-code])

### 3.1 Gaze to window (route)
`gaze/route.py:22-34` `route_target`: a window under the gaze is the target only if `confidence >= confidence_min` (default argument 0.5) and a window resolved; otherwise the focused window is used with `used_gaze=False`. `needs_confirm` (`route.py:37-44`) is true only for a destructive action that was actually gaze-routed. The decision object (`route.py:16-19`) carries `target`, `used_gaze`, `confident` and nothing about age or other modalities.

### 3.2 Targeter: freshness and layout guards
`gaze/targeter.py:100-158`: one sample per hold; a suspended topology guard returns the focused window without sampling; no sample returns the focused window; the optional grounder runs strictly after the decision is final and cannot change it (`targeter.py:155-157`). The shared-camera adapter drops any observation older than `MAX_SAMPLE_AGE_S = 0.5` s (`gaze/shared.py:70`, check at `shared.py:129`); that value's docstring ties it to the camera frame interval, and I did not find a measurement behind it. [Unknown] whether 0.5 s suits a user.

### 3.3 Deixis (voice joined to gaze)
`gaze/deixis.py:57-68` accepts only a whole utterance ("close this", "focus that window"); `deixis.py:22` makes `close` the only destructive verb; `requires_confirm` (`deixis.py:71-83`) delegates to `needs_confirm`. The daemon path (`core/daemon.py:7830-7885`) reads `targeter.last_decision`, ignores the phrase with `deixis_no_target` if there is no target, and with `[gaze] refuse_destructive_fallback` (default `False`, `config.py:618`) calls `recover(Consequence.IRREVERSIBLE, Signal("gaze", ..., usable=decision.used_gaze), focused=decision.target)` (`daemon.py:7861`). `confirm_destructive` defaults `True` (`config.py:608`). The daemon passes no `alternates` to `recover` (no `alternates` argument appears in `daemon.py`), so the "named alternate modality" rung is exercised by tests of the pure function at most; in the daemon it is unused.

### 3.4 Recovery ladder (the closest thing to an arbitration rule)
`handsfree/recovery.py:83-140` `recover`: preferred signal if usable; else the first usable alternate (for an irreversible action only an `explicit` one, i.e. the user said or pointed at it); else the focused target only for a reversible action; else a refusal with feedback. The action is never changed, only the target. Pure, total, takes no timestamps, so staleness must already be folded into `usable` by the caller.

### 3.5 Grounding resolver (voice hint, gaze point, semantic candidates)
`grounding/resolver.py:440-482` `resolve`: step 1 `_target_failure` (`resolver.py:504-518`) rejects, in a fixed order, a target below `min_target_confidence` (policy default 0.5, `resolver.py:203`), then one older than `max_target_age_s` (0.5 s, `resolver.py:207`; a non-finite clock reads as stale), then one without geometry. Candidates stale relative to the target (`max_candidate_skew_s` 0.5 s, `resolver.py:211`), off-envelope, below confidence, or contradicting the voice `IntentHint` are rejected (`resolver.py:625-650`). Candidates that cannot be separated yield `AMBIGUOUS` with the alternatives and no choice. A grounded result's confidence is `min(target, candidate)`, never a boost (`resolver.py:472-477`). The module docstring of the resolver says its numbers are unmeasured policy; I did not re-derive that here.

### 3.6 `GazeGrounder` and `refine`
`gaze/grounded.py:111-143` `refine`: the window always comes from the route decision; an `entity_id` exists only for `GROUNDED` with a non-window source. `GazeGrounder.ground` (`grounded.py:185-243`) reads the clock twice so a slow source makes the target stale and the result abstains (`grounded.py:208-227`); any exception returns `None`, which keeps window-level behaviour (`grounded.py:229-241`). **Not wired:** `GazeGrounder(` appears only in its own module and tests, and `targeter.py:39,52-56` defaults `grounder=None`; `daemon.py` passes none. Element-level grounding therefore does not run in the shipped daemon. [Verified-in-code via grep over `src/`]

### 3.7 Head pointer, face switch, and the global gate
- `headpointer/controller.py:468-531` `update` is called every tick; the global gate is sampled on new samples and asked every tick, a `clear_pending` latch drops a half-built dwell (`controller.py:484-489`), and a missing, stale or untrusted sample freezes the pointer instead of repeating the last delta (module docstring, `controller.py:15-34`; `_lost` at `controller.py:752`).
- Clutches: `set_clutch` (`controller.py:572`) freezes motion while any named clutch is held; `commit_click` (`controller.py:613`) refuses when a clutch other than the caller's own is held. The daemon's `select` action passes `own_clutches=(SWITCH_CLUTCH_SOURCE,)` (`daemon.py:2806`). This is a **head pose versus face switch** rule, written so a facial effort does not move the target it commits on.
- `facegesture/switches.py:261-268` `freeze_pointer` is a request to hold the pointer while a commit gesture is held; `switches.py:289-320` `frame` samples the gate only for frames that carry a face and releases open holds when the gate closes; `switches.py:124` `SAFE_ACTIONS` (pausing) is the only action that bypasses the gate.
- `handsfree/safety.py`: states `ACTIVE/PAUSED/FAULTED`; staleness window `DEFAULT_STALE_AFTER_MS = 500.0` (`safety.py:70`, documented in the module as not measured); per-source arming and epochs so a stale or paused source is not replayed (`safety.py:244-300`, `safety.py:351-390`); `gate` (`safety.py:392-408`) returns `allowed` plus a one-shot `clear_pending`. Only `resume` re-arms after a pause or fault; hold-only face switches may auto re-arm after a run of fresh samples (`safety.py:275-298`, `switches.py:86-100`).
- `TargetSource` (`grounding/contracts.py:210-223`) is a closed enum `GAZE, MOUSE, HEAD_POINTER, SELECTION`. Only `GAZE` is produced in `src/` (`gaze/grounded.py`); `HEAD_POINTER` and `MOUSE` have no producer outside the contract. [Verified-in-code via grep]

### 3.8 One-camera rule
ADR-v2-145 (status **Proposed**, `design/adr/adr-v2-145-shared-camera-perception.md`) invariants 1, 6, 7 (lines 51-60): one physical camera owner per daemon; failure of one derived channel does not necessarily kill the others; confidence is explicit and missing data is never read as `0,0`. Gaze and the face switch have shared-source adapters (`gaze/shared.py`, `facegesture/shared.py`) that apply when `[perception]` is on; the module text says that without it the face switch opens its own capture. Whether every combination is exercised end to end is **[Unknown]** (not run here).

## 4. Conflict cases and what the code does today

| # | Case | Current behaviour | Evidence | Gap |
|---|---|---|---|---|
| C1 | **Target ambiguity** (two controls fit the gaze region) | At window level: the one window under the gaze, or the focused window. At element level: `AMBIGUOUS` with alternatives, no choice, no entity, **but** the grounder is not wired, so this exists only as a tested library path. | 3.1, 3.5, 3.6 | In the shipped daemon, ambiguity inside a window is invisible; the window is the finest target. |
| C2 | **Stale sample** | Gaze: observations over 0.5 s are dropped, hold routes to the focused window. Resolver: target older than 0.5 s abstains `TARGET_STALE`. Head pointer: freezes. Gate: source disarmed after 500 ms without a sample, not replayed after resume. | 3.2, 3.5, 3.7 | Three separate 0.5 s constants with no shared clock contract; all **[Unknown]** as to fitness. A fallback to the *focused window* is not an abstention for a reversible action. |
| C3 | **Gaze and head targets differ** | Not handled. No code reads both. Gaze picks a window at hold start; the head pointer moves the OS pointer independently; a `select` clicks wherever the pointer is. | 3.7 (`HEAD_POINTER` unused) | Whether "look at A, point at B" should abstain, prefer one, or ask is open. |
| C4 | **Spoken "this" with a stale or low-confidence gaze** | Falls back to the focused window with `used_gaze=False`. Non-destructive verbs run on that stand-in; a destructive verb is blocked only if `refuse_destructive_fallback` is on (default off), otherwise confirm-gated only when `used_gaze` is true, so the focused stand-in runs `close` **without** a confirm by default. | 3.3, `needs_confirm` | Default configuration lets "close this" act on the focused window when gaze was not used. Whether that is intended is a maintainer question; this note does not change it. |
| C5 | **Accidental switch activation** | Detector hysteresis and `min_hold_frames` live in `facegesture/detector.py` (not re-read in depth here). A press runs only if the gate allows (`switches.py:347`); a hold is released the frame the gate closes; the pointer freezes during a commit gesture; `pause_pointer` always works. | 3.7 | Rate of false activation for real faces is **[Unknown]**; #816 owns this. |
| C6 | **Recovery after a conflict or fault** | Explicit: `resume()` re-arms and bumps the epoch, so half-made gestures and dwell are dropped; hold-only face switches may re-arm after a continuous fresh run. No cross-modal recovery state exists (nothing says "gaze and head disagreed, so wait"). | 3.7 | Recovery is per source, never per conflict. |
| C7 | **Voice names a target, gaze disagrees** | The resolver can reject a candidate that contradicts the `IntentHint`, but the hint is not produced by the daemon path (grounder unwired). Deixis grammar accepts only "this/that", not named targets. | 3.3, 3.5 | Named-target commands and gaze are never reconciled in shipped code. |

## 5. Three arbitration policies to compare (analysis only)

These are comparison candidates for a future decision, not proposals to build. None is implemented here. Each is judged on the same axes: unintended-action risk, cost of an abstention to the user, and fit with the one-camera rule.

**P0. Status quo: per-modality gates plus a recovery ladder.** Keep 3.1-3.7 as is. Abstain where a component already abstains; fall back to the focused window for reversible actions.
- For: no new behaviour; every rule is already tested in isolation (test names exist; I did not run them). Lowest risk of regression.
- Against: C3 and C7 have no rule at all; C4's default permits a destructive action on a stand-in; three independent 0.5 s windows.
- One-camera fit: neutral. It does not combine channels, so it neither benefits from nor breaks the shared source.

**P1. Explicit-authority ladder.** One ordered rule: a target the user *named or pointed at* (voice, switch-committed pointer) outranks an *inferred* one (gaze); an inferred target never authorises an irreversible action alone. This generalises `recover` (3.4) beyond deixis and wires the `alternates` argument, which the daemon leaves empty.
- For: matches the existing roadmap sentence that recovery chooses a target and never raises the consequence; deterministic, no tuning constants of its own; explainable.
- Against: needs a defined "explicit" source for the pointer (the `MOUSE` and `HEAD_POINTER` members have no producer); a head-pointer position is only explicit if the user is deliberately steering it, which cannot be known from the sample alone. [Unknown]
- One-camera fit: **weak point.** Gaze, head pose and the face switch are derived from the same camera frames (ADR-145). They share fate: a lost face makes all three stale at once, and a head turn changes both the gaze estimate and the pointer. Treating head pointer as "independent confirmation" of gaze would overstate agreement. P1 stays safe if the pointer is only ever the user's *choice*, never *corroboration*.

**P2. Abstain on conflict, then confirm.** If two modalities that both claim a target disagree (gaze window differs from the window under the head-pointer position, or voice names one and gaze another) or either is stale at action time, do nothing for reversible and nothing-plus-feedback for irreversible actions, with a one-word retry.
- For: the simplest safety property; consistent with `GROUNDED/AMBIGUOUS/UNRESOLVED` (3.5) and ADR-021's rule that a guard is judged by how rarely it fires.
- Against: it would add a guard whose firing rate on real use is **[Unknown]**; webcam gaze is described in the code as coarse (3-5 cm, `grounded.py:167-172`; roughly 1-2 degrees, `route.py` docstring), so a naive disagreement test could fire on most actions, which the project's own rule 9 warns teaches users to dismiss it. A threshold would be a new unmeasured number.
- One-camera fit: needs one timestamp domain across channels. ADR-145 gives samples with a common source timestamp, so cross-channel age comparison is possible in principle; that the shared source emits comparable timestamps for all three channels in practice is **[Unknown]** here.

**Common to all three:** any policy that needs both gaze and head pose must read them from the single camera owner, never open a second capture (ADR-145 invariant 1), and must treat a missing channel as "no signal", never as `0,0` (invariant 7).

## 6. Open questions for a human study (no recruitment, no new feature)

These are questions a future, separately reviewed study could answer. Asking them here authorises nothing.
1. How often do gaze window and head-pointer window differ during ordinary tasks, and is it noise or intent? (Needs recorded, consented sessions; today's data are synthetic or absent. See #695 and the validation matrix, which record hardware validation as unverified.)
2. Does a spoken confirm, a switch, or a second look cost the user less than a wrong action? Cost of abstention is unmeasured.
3. What staleness budget does a user tolerate across gaze (0.5 s), gate (500 ms) and pointer? All three constants are unmeasured.
4. For users who cannot speak or cannot move the head, which modality is the authority in P1? The answer is per person and may need a user-set priority, which is a product decision, not a research one.
5. Should C4's default (destructive deixis on a focused stand-in without a confirm) change? Maintainer decision; this note only records the behaviour.
6. Would elements, not windows, be worth grounding, given the grounder is unwired and the coverage of real accessibility trees (the spec's phase P3) is unmeasured?

Separate community QA from publishable human-participant research as #815 requires; this note sets up neither.

## 7. What this note does not claim

- No hardware, Wayland-wide, macOS, Windows, medical or accessibility-outcome result. No latency, accuracy or false-activation figure.
- No test was run for this note; named behaviours are read from source and docstrings, not observed.
- Not read: `facegesture/detector.py` internals, `gaze/clicks.py`, `gaze/association.py`, the `contract/` vectors, and ADR-v2-148 beyond what the code docstrings quote.
- No external standard or paper was consulted, so there is **no** Verified-primary-source claim in this note.
- Not decided: which policy (or none) to adopt. P0 is the default if nothing is decided.
