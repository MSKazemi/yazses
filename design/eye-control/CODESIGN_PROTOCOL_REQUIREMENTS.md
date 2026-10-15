# Accessibility co-design and fatigue/usability protocol — requirements (#419)

> **This is a list of what the protocol must contain. It is not the protocol.**
> It has no protocol ID, no ethics determination and no approved wording, and it authorises
> nothing: no recruitment, no session, no data collection. The responsible research team
> writes the protocol ([PAPER_EVIDENCE.md](PAPER_EVIDENCE.md) "Ethics/publication gate"),
> freezes it under #425, and obtains the applicable determination **before** the first
> participant. Every value written `<...>` below is a decision that belongs to them and to that
> determination, not to this file.

**Why this file exists.** #419 says hands-free defaults are not recommended until structured
usability and fatigue evidence exists. The pieces of a protocol are scattered over
[RESEARCH_PARTICIPANT_TEMPLATE.md](RESEARCH_PARTICIPANT_TEMPLATE.md),
[VALIDATION_MATRIX.md](VALIDATION_MATRIX.md), [METRICS.md](METRICS.md) and
[DATA_SHARING.md](DATA_SHARING.md), and several elements a fatigue study cannot run without are
written nowhere. This file states, per element, what already exists (quoted, so a test can check
the quote is still there) and what is absent (so a test can check it is still absent, and force
this file to change the day it is not).

**This is not a medical study** (#419). Nothing here requests a diagnosis or infers capability
from a participant; it tests the interaction and the recovery tasks.

## Element register

`file :: phrase` in a *Provided today* cell is a verbatim phrase that must still be in that file.
`absent :: term` in an *Absent today* cell is a word that must still appear in **no** other file
in this directory; adding it elsewhere is progress, and the way to record that progress is to
move the element to *Provided today* here.

| # | Element | Provided today | Absent today | The frozen protocol must still specify |
|---|---|---|---|---|
| 1 | Measures | `METRICS.md :: Use a frozen questionnaire/scale in the study protocol`<br>`METRICS.md :: fatigue/change over session`<br>`PAPER_EVIDENCE.md :: participant-reported comfort/fatigue` | `absent :: NASA-TLX`<br>`absent :: Borg` | the named scale(s) and exact item wording; when each is asked — #419 asks for a participant-chosen comfort/fatigue rating **before and after**; that any item may be declined; the task measures per modality ([METRICS.md](METRICS.md) "Protocol coverage") |
| 2 | Session length and exposure | `EVALUATION.md :: Scripted duration: approximately 10–20 minutes.`<br>`RESEARCH_PARTICIPANT_TEMPLATE.md :: Expected duration:` | `absent :: maximum continuous` | maximum continuous exposure per modality, maximum total session, and exposure recorded per modality (a fatigue finding without its exposure is uninterpretable) |
| 3 | Rest rules | `RESEARCH_PARTICIPANT_TEMPLATE.md :: You may pause, recalibrate, switch modality or stop.` | `absent :: scheduled break`<br>`absent :: rest break` | whether rests are scheduled or on request, minimum rest between blocks and between modalities, that rest time is excluded from performance time, that taking a rest never costs compensation |
| 4 | Stopping rules | `VALIDATION_MATRIX.md :: participant/tester is uncomfortable or fatigued`<br>`RESEARCH_PARTICIPANT_TEMPLATE.md :: You may pause or stop at any time.`<br>`RISK_REGISTER.md :: User cannot stop continuous camera control` | `absent :: facilitator` | the list of conditions on which the facilitator **must** stop the session (proposed minimum below), who may resume it, and that a stop is recorded as `participant_stopped`, never as a failed trial |
| 5 | Adverse-event handling | `RESEARCH_PARTICIPANT_TEMPLATE.md :: Possible discomfort or risk` | `absent :: adverse`<br>`absent :: incident` | what counts as an adverse event or unanticipated problem, the immediate response, who records it and where (never in a public GitHub issue), who must be told under the ethics determination, and follow-up contact |
| 6 | Accessibility of the protocol itself | `RESEARCH_PARTICIPANT_TEMPLATE.md :: The study must provide a stop/pause method that does not depend on accurately controlling the experimental pointer.` | `absent :: alternative format`<br>`absent :: large print`<br>`absent :: time pressure`<br>`absent :: untimed`<br>`absent :: read aloud` | alternative formats of the information sheet, consent and questionnaires; an alternative response channel that does not need the pointer under test; untimed, self-paced instructions; the facilitator's assistance rule; seating, camera position and schedule flexibility |
| 7 | What consent covers | `RESEARCH_PARTICIPANT_TEMPLATE.md :: Do not bundle optional public release or quotation into one mandatory checkbox`<br>`DATA_SHARING.md :: separate optional permission for anonymous verbatim comments`<br>`RESEARCH_PARTICIPANT_TEMPLATE.md :: Raw consent/contact records are never published.` | `absent :: co-design consent` | the final approved consent mechanism; for co-design sessions held **outside** #425, either no quotation or a separate quotation consent (#419: "consent for any quote"); re-confirmation after a stop |

## Proposed minimum facilitator-must-stop conditions

These are the conditions the existing documents already imply, collected so the protocol cannot
omit one. **They are a proposal for the research team to adopt, amend or reject; no numeric
threshold is set here.**

1. The participant asks to pause, stop or withdraw, by any channel the protocol offers — an
   instruction to continue is never given in reply.
2. The participant reports or shows pain, strain or distress (eyes, neck, face, frustration).
   (VALIDATION_MATRIX "Stop conditions": uncomfortable or fatigued.)
3. The independent stop path does not work when invoked. The session ends at once; this is R-05,
   a release blocker, not a data point. (RISK_REGISTER R-05.)
4. The pointer or switch performs an unintended action the participant cannot undo or is upset by,
   or such actions repeat beyond `<N, set by the protocol>`. (R-03, R-04.)
5. Recovery from tracking or camera loss re-fires an action. (R-24.)
6. The task would expose private desktop content; a session uses non-sensitive demo content only.
   (RESEARCH_PARTICIPANT_TEMPLATE "Possible discomfort or risk".)
7. Camera permission cannot be granted, or the feature is not implemented on that platform.
   (VALIDATION_MATRIX "Stop conditions"; a BLOCKED result is evidence.)
8. Any doubt on the facilitator's part about the participant's wellbeing.

## What must be reported, per #419 "Replication dimensions"

Number of distinct people, sessions, physical computers, OS/session coverage, camera classes,
display scaling/topology, and exposure time per modality. "12 runs" is never summarised without
saying which of those it counts.

Two of these cannot be answered from the machine-readable record today, and should not be
described as if they could:

- **Distinct people.** The result schema (`yazses.eyeeval.schema`) has no participant or session
  field, and the validation registry and coverage page deliberately carry no identity. The
  research dataset's `participant_id` and `session_id` ([METRICS.md](METRICS.md) "Human-study
  identifiers") have nowhere to live in a `community_qa` result.
- **Exposure per modality.** Only the face-switch task emits an exposure (`scored_duration_s`);
  the Head-Pointer task emits `accidental_click_count_total` with no exposure to put it over
  ([METRICS.md](METRICS.md) "Defined, not yet emitted": `exposure_s`).

## Before any hands-free default is recommended

Nothing in the repository recommends a hands-free default, and the gate that would allow it is
[GOVERNANCE.md](GOVERNANCE.md) Gate 7 together with the "Recommendation blockers" of
[RISK_REGISTER.md](RISK_REGISTER.md): more than one environment and person, a measured
false-activation and accidental-click rate, usability and fatigue evidence (R-18, R-23), and no
unresolved high-severity risk. The hands-free preset states that every value it sets is
provisional, and the user-facing pages that mention a camera feature say it is experimental.
`tests/test_eye_acceptance_consistency.py` checks the second sentence against the feature
registry, so it cannot drift back into a recommendation unnoticed.

Community co-design or QA that is not run under #425 stays out of participant-level analysis
([DATA_SHARING.md](DATA_SHARING.md)). It can support product decisions and name failures for the
controlled study to investigate.
