# Hands-free fatigue, precision and task-completion measurement protocol (proposal)

**Date:** 2026-11-06 · **Baseline:** `main` at `8a72bbc6` · **Issue:** [#817](https://github.com/MSKazemi/yazses/issues/817) (NEXT-A11Y-05), epic [#790](https://github.com/MSKazemi/yazses/issues/790)
**Status:** Research draft, **proposal only**. Not a frozen study plan, not a preregistration, not an ethics submission. ADR-030 hands-free freeze unchanged. No ADR status changes.
**Siblings (cite, do not re-decide):** [#813 task inventory](2026-11-05-handsfree-task-inventory-and-evidence-gaps.md) · [#816 stop / unintended-activation threat model](2026-11-05-emergency-stop-and-unintended-activation-threat-model.md) · [#815 arbitration](2026-11-06-multimodal-arbitration-comparison.md) · #814 co-design, consent and review gates (note `2026-11-06-codesign-consent-and-review-gates.md`, on an unmerged branch at the time of writing) · #818 Wayland/AT limits · #819 go/no-go. Coordinates with [#419](https://github.com/MSKazemi/yazses/issues/419), [#425](https://github.com/MSKazemi/yazses/issues/425), [#426](https://github.com/MSKazemi/yazses/issues/426) as #817 asks. Delivery stays in [#102](https://github.com/MSKazemi/yazses/issues/102) / [#692](https://github.com/MSKazemi/yazses/issues/692).

**Nothing here authorizes** recruitment, recording, sensor upload, a participant session, a runtime capability, or a ThinkGear/EEG runtime (#827 open). No data collection may start until the ethics/review and consent gates in section 9 are met.

## 1. Question and answer in one paragraph

#817 asks which measures — success, time, actions per task, target errors, false triggers, intervention, recoverability and voluntary comfort — show utility beyond recognition WER. **Proposed answer:** a hands-free system is useful to a person only if they can *finish a task, without help, without the system acting when they did not mean it, and stop it when they need to*. WER predicts none of those four directly: a perfect transcript can still land in the wrong window, a stop phrase can be recognised and still arrive too late, and a pointer can be accurate and still exhaust the neck in ten minutes. This note therefore proposes (a) **three primary outcomes** — unassisted task completion, unintended actions per usable exposure hour, and independent-stop success — with WER demoted to a covariate; (b) a **two-tier protocol**: a deterministic synthetic/replay tier that can run in CI today on the existing `eyeeval` machinery, and a human tier that stays blocked behind #814/#425; (c) **estimation, not significance testing**, with sample size justified by precision and resource constraints rather than by a power calculation nobody can honestly parameterise; and (d) **stop rules written before the first session**. [Proposal] throughout unless labelled otherwise.

## 2. Method and labels

Read: #817 issue body (2026-11-06), the #813/#815/#816 notes, the #814 note on its branch, `design/eye-control/{METRICS,PAPER_EVIDENCE,CODESIGN_PROTOCOL_REQUIREMENTS,RISK_REGISTER,VALIDATION_MATRIX,GOVERNANCE}.md`, and `src/yazses/eyeeval/` and `src/yazses/handsfree/` where cited. External sources were located by web search on 2026-11-06; titles/DOIs were confirmed against publisher or index listings, but the papers' full texts were **not** re-read for this note.

Labels: **[Verified-in-code]** read at `8a72bbc6`, cited file:line · **[Verified-in-docs]** read in a repository document · **[External]** published source, citation confirmed, text not re-read · **[Proposal]** this note's suggestion · **[Unknown]** no evidence either way. No test was run for this note.

## 3. What already exists (do not re-decide)

- **The hands-free workflow metric list already exists.** `design/eye-control/METRICS.md:285-302` lists task completion, completion time, unintended action count, recovery action count, fallback modality, keyboard/mouse intervention, pause/kill invoked, recover-from-camera-loss, plus optional ease/comfort/fatigue/preference, and says to "use a frozen questionnaire/scale". [Verified-in-docs] This note **operationalises** that list (denominators, units, instruments, analysis); it does not replace it.
- **Within-participant, counterbalanced, participant as the unit, no n=8 by habit.** `PAPER_EVIDENCE.md:115-131`: pilot data flagged `pilot=true` and excluded from confirmatory analysis, no tuning on pilots, "prefer a within-participant design … with counterbalanced order", "the exact sample size must be justified by the planned analysis/effect/precision target", "independent unit is usually the participant". [Verified-in-docs]
- **The protocol gaps are already named.** `CODESIGN_PROTOCOL_REQUIREMENTS.md:32-38` marks as absent: a named scale (NASA-TLX, Borg), maximum continuous exposure, scheduled rests, a facilitator-must-stop list, adverse-event handling, accessible formats, and co-design consent; `:40-59` proposes eight facilitator-must-stop conditions with no numeric thresholds. [Verified-in-docs] Sections 6 and 8 below fill the measurement-side gaps (scales, exposure, rests) and adopt the stop list.
- **Two record fields the human tier needs do not exist.** No participant/session field in `yazses.eyeeval.schema`, and the Head-Pointer task emits `accidental_click_count_total` with no exposure (`CODESIGN_PROTOCOL_REQUIREMENTS.md:65-76`; `src/yazses/eyeeval/runner.py:489`). [Verified-in-docs/code]
- **A rate without a denominator is already refused in code.** Face-switch replay reports phantom actions per hour over a scored duration (`src/yazses/eyeeval/runner.py:306-316`, `:493-508`); an empty trace is an error precisely because `0.0` per hour over nothing reads like a perfect switch (`src/yazses/eyeeval/switch_trace.py:43-50`); `src/yazses/eyeeval/analysis.py:45` and `:172-180` return `INSUFFICIENT` below a minimum n or exposure, and `:15` calls those minimums "provisional reporting" floors, not power calculations. [Verified-in-code] The human tier should keep exactly that discipline.
- **Every stop-path threshold is unmeasured.** E.g. `DEFAULT_STALE_AFTER_MS = 500.0` "Unmeasured" (`src/yazses/handsfree/safety.py:68-69`); stop-phrase recognition "unmeasured" (`src/yazses/handsfree/stopword.py:31-34`). [Verified-in-code] #816 G1/G4/G5 lists them. The protocol must measure, not assume, them.
- **The #817 issue's EEG addendum** (2026-11-03, synthetic-only) asks future designs to report predeclared false candidates per *usable* idle hour with bounds, valid/suppressed exposure, calibration time, time-to-stable candidate, false-action cost, independent pause/stop, per-user completion and failures, and never to substitute a percent classification accuracy or a synthetic rate for a field report. [Verified-in-docs] Adopted below; any biosignal arm stays unauthorized (ADR-030, #827).

## 4. Research questions and what would falsify the proposed answer

| RQ | Question | Falsifying / decisive evidence |
|---|---|---|
| RQ1 | Can a person who does not use a keyboard or mouse complete the four task families of #813 (edit text, navigate an app, answer a dialog, stop and recover) **unassisted**, per modality configuration? | Per-participant completion with intervention recorded. If WER alone predicts completion well (e.g. completion is ordered exactly by WER across configurations and participants), the "beyond WER" premise is weakened. |
| RQ2 | How often does the system act when the person did not intend it, per usable exposure hour, by modality and by state (dictating, idle, talking to someone)? | A zero count over a stated exposure gives an upper bound (section 7); a non-zero count with exposure is a finding. A rate quoted without exposure is not evidence. |
| RQ3 | Does the independent stop work every time, how long does it take, and does recovery re-fire anything? | One failed independent stop is decisive (R-05, release blocker), not a data point to average. |
| RQ4 | How do effort and self-reported fatigue/comfort change over a session and between modalities, at the exposure actually used? | A comfort decline that tracks exposure, not configuration, would argue for session limits rather than a different modality. |
| RQ5 | How precise is targeting (wrong-target actions vs grounded-correct vs abstained) in realistic dialogs? | Wrong-target actions on a destructive control at any rate is a no-go signal for that route, independent of averages. |

## 5. Measures (operational definitions)

Unit of analysis: **participant** (tasks nested in participants). Every count is reported with its denominator. "Usable" exposure = time the modality was enabled and its sensor valid (not FAULTED, not PAUSED, not in a rest), mirroring the EEG addendum's "valid/suppressed exposure". [Proposal]

| # | Measure | Definition and unit | Why it adds information beyond WER | Synthetic tier? | Human tier? |
|---|---|---|---|---|---|
| P1 | **Unassisted task completion** (primary) | Per task attempt: `completed_unassisted` / `completed_assisted` / `not_completed` / `participant_stopped`. Assisted = any keyboard, mouse, terminal or helper action (#813 7c item 6). `participant_stopped` is never a failure (`CODESIGN_PROTOCOL_REQUIREMENTS.md:35`). Report per participant k/n and pooled. | A task can fail on routing, focus, a missing hands-free entry point, or a dialog, with perfect transcription. | Yes: scripted scenario reaches the end state without a non-hands-free event. | Yes |
| P2 | **Unintended actions per usable exposure hour** (primary) | Count of system actions (keystroke burst, click, focus change, command) not intended by the participant, ÷ usable exposure hours, split by state (dictating / idle / conversing / resting-but-armed). Intent judged by the participant immediately ("did you mean that?"), facilitator records; disagreement recorded, participant's view wins. Zero is reported as an upper bound (section 7). | Covers false wake, phantom switch, echoed prompt, misrouted text: none is a word error. | Yes: `eyeeval.switch_replay` already yields phantom/h on traces; extend the same shape. | Yes |
| P3 | **Independent-stop success and latency** (primary) | Per scripted stop probe: success yes/no; time from cue to "all actions denied" (from local event log), per stop route. Plus `no_replay`: after resume, zero actions from pre-stop state (#813 7c item 4). | The stop phrase being transcribed correctly says nothing about whether it arrives in time (#816 G1). | Yes (#816 S2 latency model with fake clock). | Yes |
| S1 | Active task time | Seconds from task cue to end state, excluding rests and facilitator pauses. Median and range per participant; never pooled across participants without the participant-level view. | Captures correction loops and dwell waits. | Model only | Yes |
| S2 | Actions per task | Count of user-issued actions (utterances, switch presses, dwell clicks) per completed task; report ratio to the scripted minimal count for that task. | Text-entry KSPC-style efficiency; separates "worked, but took 40 utterances". | Yes | Yes |
| S3 | Target precision | Per targeted action: grounded-correct / wrong-target / ambiguous-abstained / no-target. Wrong-target on a destructive control reported separately, always. Abstention is not an error (#813 S6). | Routing and grounding are downstream of ASR. | Yes (#813 S6 fake AT-SPI dialog) | Yes |
| S4 | Recoverability | Per injected disturbance (camera covered, device unplugged, dialog appears, lock/suspend where safe): recovered hands-free yes/no, recovery time, actions needed. | Recovery routes are where #813 found hands-free gaps (resume needs CLI/panel). | Yes (#813 S1-S4) | Yes |
| S5 | Intervention count | Number and kind of non-hands-free inputs and helper actions per session. | Direct measure of independence. | n/a | Yes |
| S6 | Voluntary comfort / fatigue | Participant-chosen rating before the session, after each block and at the end (section 6). Every item declinable. | Utility over a working day, not one minute. | No | Yes |
| C1 | WER / CER (covariate) | On the task utterances, computed locally from the facilitator's reference script; reported as a covariate of P1-S3, not as an outcome. | — | Yes | Yes, local only |
| C2 | Calibration and setup time | Seconds to a usable configuration, and number of recalibrations. EEG addendum's "time-to-stable candidate" applies only to a future, separately authorized biosignal arm. | Setup cost is part of utility. | Partly | Yes |

Not used as outcomes: percent classification accuracy, a single pooled "accuracy %", or any synthetic rate presented as field performance (#817 addendum). [Proposal]

## 6. Instruments

**6.1 Local event log (both tiers).** A run record in the existing `eyeeval` result shape, extended with fields that are **absent today** [Verified-in-docs, section 3]: `participant_code` (study-local pseudonym, never in a public artefact), `session_id`, `exposure_s` per modality with `usable_s`/`suppressed_s`, `task_outcome` (P1 values), `intervention[]`, `stop_probe[]`. Content restriction follows `src/yazses/handsfree/observability.py` (names, states, ages, counts; never a coordinate, frame, transcript or window title) [Verified-in-code, module docstring]. Adding these fields is a schema change and needs maintainer approval under the freeze; this note does not make it.

**6.2 Facilitator sheet.** Paper or accessible form: task cue time, P2 intent judgement per action ("intended / not intended / unsure"), interventions, stop probes, adverse events (never in a public GitHub issue, `CODESIGN_PROTOCOL_REQUIREMENTS.md:36`).

**6.3 Subjective scales (fills the "absent :: NASA-TLX / Borg" gap).** Proposal, for the research team to adopt or replace:

- **Primary comfort item, participant-chosen anchor**: a single 0-10 rating "how comfortable is using this right now?", asked before, after each block and at the end (#419 asks for before-and-after). Delivered by whichever response channel the participant chooses (spoken, switch, partner-assisted scanning), *not* the modality under test (`CODESIGN_PROTOCOL_REQUIREMENTS.md:37`).
- **Localised effort: Borg CR10** for neck, eyes, voice/throat separately, after each block. [External] Borg G., "Psychophysical bases of perceived exertion", *Med Sci Sports Exerc* 14(5), 1982 (citation from memory; not re-verified 2026-11-06). Licence terms of the scale wording must be checked before use. [Unknown]
- **Workload: NASA-TLX, raw (unweighted) variant**, once per configuration. [External] Hart & Staveland 1988 and the 2006 update are listed on NASA's TLX publications page, https://humansystems.arc.nasa.gov/groups/tlx/publications.php (accessed 2026-11-06). Raw TLX keeps the session shorter than the weighted pairwise procedure. The "Physical demand" item is the one most relevant to fatigue.
- **Satisfaction with the assistive technology (optional, end of study): QUEST 2.0**, 12 items, device + services. [External] Demers, Weiss-Lambrou & Ska, *Technology and Disability* 14(3):101-105, 2002, https://doi.org/10.3233/TAD-2002-14304 (accessed 2026-11-06). Licensing/permission [Unknown]; skip if not cleared.
- **Every item may be declined** and a declined item is recorded as `declined`, not imputed.

Pointing throughput (Fitts/ISO 9241-411 style) stays optional and preregistered-only, as `METRICS.md:226` already says; it is not proposed as a primary outcome because pointing is one sub-step of the task families.

## 7. Sample size and analysis reasoning

**The honest justification is precision under a resource constraint**, two of the six routes in [External] Lakens, "Sample Size Justification", *Collabra: Psychology* 8(1):33267, 2022, https://doi.org/10.1525/collabra.33267 (accessed 2026-11-06). An a-priori power analysis is not proposed: there is no prior effect size for any of P1-P3 in this population, and inventing one would be a number nobody measured (the house rule the eyeeval code already follows). The CHI convention is not a justification either: the modal CHI 2014 sample size was 12 ([External] Caine, CHI '16, https://doi.org/10.1145/2858036.2858498, accessed 2026-11-06) — a description of habit, and `PAPER_EVIDENCE.md:129-130` already rules out choosing n=8 for that kind of reason.

**What a given n buys (P1, binary completion, 95% Wilson interval; computed for this note):**

| Participants | Observed | 95% interval | Width |
|---|---|---|---|
| 6 | 4/6 | 0.30-0.90 | 0.60 |
| 8 | 6/8 | 0.41-0.93 | 0.52 |
| 12 | 9/12 | 0.47-0.91 | 0.44 |
| 16 | 12/16 | 0.51-0.90 | 0.39 |
| 24 | 18/24 | 0.55-0.88 | 0.33 |

Reading: below ~12 people, a pooled completion proportion cannot separate "most people can" from "about half can". So for a small study the **primary report is per-participant** (each person's k/n tasks, with assisted vs unassisted), and pooled proportions are descriptive with their interval. If the study cannot reach the n it needs for a pooled claim, it says so (Lakens's "acknowledge the absence of a justification" route is legitimate; dressing a small n as confirmatory is not).

**Zero unintended actions (P2) is a bound, not a zero.** With 0 events over T usable hours, the one-sided 95% upper bound on a Poisson rate is −ln(0.05)/T ≈ 3/T per hour: 0.5 h → ≤6/h, 1 h → ≤3/h, 3 h → ≤1/h, 10 h → ≤0.3/h. The binomial analogue for "0 of n" is the rule of three, [External] Hanley & Lippman-Hand, *JAMA* 249(13):1743-1745, 1983, https://doi.org/10.1001/jama.1983.03330370053031 (accessed 2026-11-06). Consequence: a target such as "fewer than 1 unintended action per hour" needs **at least ~3 usable hours of zero events per configuration** (pooled across people only if per-person exposure is also shown). That exposure figure, not the head count, is what sizes the P2 arm; it also collides with fatigue limits, so exposure must be spread across sessions, which is why section 8 caps continuous exposure.

**P3 (independent stop):** not estimated as a rate at all. One failure halts the study (section 8). The number of stop probes per session is fixed in advance and reported.

**Analysis (descriptive-first, preregistered):** per-participant tables and plots for P1-S6; mixed-effects models (participant random intercept) only as a secondary, descriptive summary when n allows; no p-value-driven claims; no exclusion of a participant for "poor performance"; pilot data excluded from confirmatory tables (`PAPER_EVIDENCE.md:115-119`). **Alternative design to evaluate:** a single-case experimental design (repeated measures within one person across phases) may fit a small, heterogeneous population better than a group design; the choice belongs to the research team and the ethics body. [Proposal; no source re-read]

## 8. Session design, counterbalancing and stop rules

**Configurations** (only features that exist and are opt-in; nothing new): e.g. A voice-only hold-to-talk with a switch, B voice + face switch, C voice + head pointer with dwell. Exact set chosen with co-design partners (#814), not by the developer.

**Counterbalancing:** Williams design for first-order carry-over: with k configurations, k orders when k is even, 2k when k is odd; participants assigned to orders in rotation. [External] Williams E.J., 1949, https://doi.org/10.1071/CH9490149 (accessed 2026-11-06; CSIRO lists the journal name inconsistently). With k=3 that is 6 orders, so n should be a multiple of 6 to balance fully; otherwise report the imbalance.

**Session structure:** setup/calibration (C2) → practice block (`pilot`-style, not scored) → scored blocks per configuration, each containing the four task families of #813 with non-sensitive demo content → stop probes at pre-declared random points inside blocks → comfort/Borg after each block → raw TLX per configuration.

**Exposure and rest parameters** (fill the `absent :: maximum continuous` / `scheduled break` gaps, `CODESIGN_PROTOCOL_REQUIREMENTS.md:33-34`): the protocol must fix `<max continuous exposure per modality>`, `<max total session>`, `<minimum rest between blocks>` and `<minimum rest between modalities>` **with co-design partners before the first session**; this note sets no number because none is measured. Rest is on request at any time *and* scheduled; rest time is excluded from S1 and from usable exposure; rest never costs compensation.

**Stop rules.**

1. *Session level — adopt verbatim* the eight facilitator-must-stop conditions of `CODESIGN_PROTOCOL_REQUIREMENTS.md:40-59` (participant asks; pain/strain/distress; independent stop fails; unintended action the participant cannot undo or repeated beyond `<N>`; recovery re-fires an action; private content exposed; permission/platform blocked; any doubt about wellbeing). A stop is recorded as `participant_stopped` or `facilitator_stopped`, never as a failed trial.
2. *Block level:* a comfort rating that falls by `<Δ, set with partners>` from that day's baseline, or a Borg CR10 rating at or above `<threshold>`, ends the block and triggers a rest; the participant may continue only if they choose to.
3. *Study level (halt, review, then decide):* (a) any independent-stop failure in any session (R-05); (b) any unintended destructive action that reached an application; (c) any adverse event under the ethics determination; (d) recovery re-firing an action twice in the study. Resumption requires a written root cause and the ethics body's agreement where the determination requires it.
4. *No early stopping for success.* The study is estimation; an early "looks good" ends nothing.
5. *Futility signal for #819:* if, after the planned sessions, no participant completes the stop-and-recover task family unassisted in any configuration, that is reported as a no-go input for hands-free recovery as currently built (#813 gap 1), not averaged away.

## 9. Consent, ethics and data hooks (gates; nothing starts here)

- **Hard blocker:** no responsible research institution is named, so no ethics determination can exist (#814 note §1). No recruitment, recording or session before #425 / #427 / #814 gates are met.
- **Consent channel for people who cannot sign, click or type**, and the helper's role and data (#814 R3), must be settled before the instrument list above is final, because every subjective item depends on that channel.
- **Microphone and biosignal data classes** (#814 R6): this protocol needs *no* retained audio, video or biosignal. WER (C1) is computed locally during the session and only the numbers are kept; if the ethics body requires no transcript at all, C1 is dropped rather than retained. Raw camera stays in memory as today (`handsfree/observability.py`). Any biosignal arm is out of scope (ADR-030, #827).
- **Retention** (#814 R7): the event log and facilitator sheet carry a retention period and deletion trigger set by the institution; the pseudonym-to-person mapping is never published and is deleted at the withdrawal cutoff.
- **Withdrawal:** at any time, by any channel; data handling on withdrawal as the consent text states.
- **Community QA vs research:** community QA (validation slots, #428 family) may report P1-P3 *system* observations without participant identifiers; it is never merged into participant-level analysis (`CODESIGN_PROTOCOL_REQUIREMENTS.md:89-91`, `DATA_SHARING.md`).
- **Coding agents:** no real participant data, audio or transcript is given to a third-party coding agent (AGENTS.md account-safety rules).

## 10. Synthetic and replay tier (participant-independent; can be built without people)

Purpose: fix the metric definitions and analysis code *before* any person is measured, and catch regressions. Each item reuses the #813 §7a / #816 §S scenarios and emits the **same field names** as the human tier with `synthetic=true`, so the analysis code is exercised end to end and synthetic numbers can never be mistaken for field ones.

| ID | Emits | Built from |
|---|---|---|
| R1 | P2 phantom/h with exposure, per nuisance segment | `src/yazses/eyeeval/switch_replay.py` (exists) |
| R2 | P3 stop latency as a function of scripted decode time | #816 S2 fake-clock model |
| R3 | S4 recovery outcome, `no_replay` after resume | #813 S1-S4, `tests/test_handsfree_e2e_fake_scenario.py` pattern |
| R4 | S3 grounded-correct / wrong-target / abstained | #813 S6 fake AT-SPI dialog |
| R5 | P1 reachability: can the task's first step be produced by the configuration at all | #813 S5 entry-point census |
| R6 | Analysis self-test: given fixture logs with known counts and exposures, the report shows the Wilson interval, the 3/T bound and `INSUFFICIENT` below floors | `src/yazses/eyeeval/analysis.py` floors |

Each needs maintainer approval under the ADR-030 freeze (a new scenario harness is scope); none is implemented by this note.

## 11. Accessible, non-medical reporting guidelines

- Plain language; describe what people did and what the system did, not impairments or diagnoses. Report only the access methods a participant chose to share.
- Lead with per-participant results; a pooled number always comes with n, the interval and the participant-level view.
- Every rate carries its exposure; every zero is an upper bound; every "assisted" completion is labelled as such.
- Never a single "accuracy %"; never a synthetic or CI number in the same table as a human one.
- No clinical, therapeutic or compliance claim (no WCAG/508/EN 301 549 statement from this study).
- Report replication dimensions as `CODESIGN_PROTOCOL_REQUIREMENTS.md:61-76` requires: distinct people, sessions, computers, OS/session, camera classes, display topology, exposure per modality.
- Disagreements between participant and facilitator (P2 intent) are reported, not resolved silently.
- Publish the report in accessible formats (screen-reader-checked text, not image-only tables).

## 12. Preregistration checklist (to freeze before the first non-pilot session)

- [ ] Configurations and their exact config values (versions, commit).
- [ ] Task scripts with minimal action counts (for S2) and demo content.
- [ ] Primary outcomes P1-P3 and their exact definitions as in section 5.
- [ ] Scales, wording, delivery channel and timing; declinable.
- [ ] Exposure and rest parameters, numeric, agreed with co-design partners.
- [ ] Stop-rule thresholds `<N>`, `<Δ>`, `<threshold>`.
- [ ] Williams orders and assignment rule.
- [ ] Sample-size justification route (precision / resources / acknowledged absence) and the target usable exposure per configuration for P2.
- [ ] Analysis code tested on the synthetic tier (R6) before data exist.
- [ ] Ethics determination reference, consent mechanism, retention and deletion trigger.
- [ ] Pilot handling (flagged, excluded, no threshold tuning carried into the confirmatory set).

## 13. Failure modes of this protocol and alternatives not chosen

- **Exposure collides with fatigue.** The P2 bound needs hours; comfort needs short blocks. Mitigation: multi-session exposure accumulation; if it is infeasible, report the achieved bound honestly instead of a target.
- **Intent judgement is subjective** (P2). Mitigation: immediate participant judgement, recorded disagreements, and a replay of the local event log the participant can review (states and names only).
- **Ceiling/floor effects:** if every configuration fails the stop-and-recover family, the comparison is uninformative; that is still a decisive #819 input.
- **Facilitator help leaking into "unassisted".** Mitigation: any facilitator action is an intervention (S5) by definition.
- **Alternatives:** WER-only benchmark (rejected: answers a different question); lab-only Fitts throughput (kept optional); diary/field study over weeks (stronger ecological validity, larger privacy load; a candidate *after* this protocol, not instead); single-case experimental design (section 7, open).

## 14. ADR position

No ADR change is proposed. This note feeds #819 (go/no-go) with a measurement model; it does not authorize implementation, a schema change, a study, or lifting the ADR-030 freeze. ADR-v2-150 stays Proposed.

## 15. Explicit non-claims

- No user study, no participant data, no measurement of any person; no session was run.
- No numeric threshold for comfort, exposure, rest or unintended actions is set; placeholders stay placeholders.
- No accessibility-compliance, clinical or safety-certification claim.
- External sources were not re-read in full for this note; a citation marked "from memory" must be checked before it is quoted.
- The Wilson and Poisson figures in section 7 are arithmetic on hypothetical counts, not results.
