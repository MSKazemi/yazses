# Eye / camera control — paper evidence plan

This document defines what evidence YazSes should collect **if** the eye/hands-free programme is
eventually used in a research paper.

It does not authorize participant recruitment. Human-data collection begins only after the relevant
ethics/review determination and consent materials are in place.

## Why collect structured evidence now?

The repository already has:
- a paper benchmark harness with machine provenance;
- cross-platform GitHub Actions benchmark runs;
- gaze research/specification;
- pure control algorithms.

The missing empirical contribution is human/task evidence: YazSes has explicitly documented that it
has not yet run a controlled human-participant HCI study.

We should therefore build **paper-ready instrumentation now** but distinguish engineering QA from
paper-eligible human data.

## Candidate paper questions

Do not try to answer all of these in one first paper.

### RQ1 — Can commodity-webcam gaze reliably choose a coarse dictation target?

Primary outcomes:
- correct-window/pane rate;
- wrong-target rate;
- fallback rate;
- calibration error/drift.

Factors:
- person;
- camera/computer;
- OS/session;
- glasses optional;
- lighting;
- display scaling/topology.

### RQ2 — Can webcam head pose + an explicit commit modality support hands-free pointer tasks?

Primary:
- task completion;
- movement time;
- miss rate;
- accidental clicks/hour;
- recovery success.

Secondary:
- pauses/recenters;
- tracking loss;
- participant-reported comfort/fatigue.

### RQ3 — Which deliberate face gestures are usable as low-false-activation switches?

Primary:
- false activations/hour;
- miss rate;
- activation latency.

Conditions:
- deliberate activation block;
- neutral block;
- normal speaking block.

This is especially important for mouth-open: speech itself is a confound.

### RQ4 — Does multimodal composition complete a realistic hands-free workflow?

Primary:
- workflow completion without keyboard/mouse;
- unintended actions;
- recovery/fallback count;
- total time.

This should be attempted only after individual components are stable.

## Recommended first paper scope

The cleanest first empirical paper is likely:

> **Coarse gaze targeting + multimodal commit on commodity webcams: reliability, fallback and
> cross-platform evidence for a privacy-local voice interface.**

Why:
- gaze routing already exists;
- it has an honest coarse target scope;
- correct/wrong/fallback outcomes are objective;
- it does not require claiming full hands-free desktop control before Head-Pointer/face-switch mature.

Head-Pointer/face-switch could be a second study or a later section only if they reach stable
experimental status before data collection freezes.

## Study structure

### Phase A — non-human reproducibility

Archive:
- exact commit/release;
- dependency lock;
- protocol/tasks;
- synthetic traces;
- CI matrix;
- result schema;
- analysis code.

### Phase B — pilot

Small internal/pilot sample to test:
- instructions;
- task length;
- logging;
- calibration;
- safety/stop behavior.

Pilot data should be flagged `pilot=true` and excluded from confirmatory analysis unless the
preregistered plan explicitly allows otherwise.

Do not tune thresholds on pilot participants and then quietly count them as independent confirmation.

### Phase C — main study

Prefer a within-participant design for modality/config comparisons when reasonable, with
counterbalanced order.

The exact sample size must be justified by the planned analysis/effect/precision target; do not
choose n=8 merely because an older roadmap mentioned it.

Independent unit is usually the **participant**, not each trial.

### Phase D — cross-platform replication

If the main study cannot realistically run every participant on every OS, separate:
- controlled human comparison on a standardized setup;
- cross-platform hardware replication on additional machines.

Do not confound OS with person and then claim an OS effect.

## Data table design

### participant table — private/restricted

Only what protocol requires:
- random participant ID;
- consent/protocol status;
- optional study-relevant demographics if justified;
- contact/withdrawal mapping stored separately.

Do not put this table in Git.

### session table — de-identified

- participant ID;
- session ID;
- software/commit;
- OS/session;
- computer/camera class;
- display geometry;
- config;
- calibration version;
- lighting category;
- optional glasses category;
- start/end/duration;
- technical validity/exclusion reason.

### trial/event table

Gaze:
- intended target;
- outcome correct/wrong/fallback;
- confidence;
- response/routing time;
- calibration-relative time.

Head pointer:
- target geometry;
- movement time;
- click/miss;
- accidental click;
- tracking loss.

Face:
- requested gesture;
- detected/missed;
- false event context;
- latency.

No private screen content.

### questionnaire table

Only if research protocol includes it:
- frozen item IDs;
- numeric response;
- optional comment stored separately when quote consent differs.

## Conditions worth balancing/stratifying

Do not collect all as demographics by habit; collect only variables tied to a hypothesis or
reliability check.

Possible:
- OS/session;
- camera type;
- display scale;
- monitor topology;
- lighting;
- glasses;
- viewing distance;
- feature configuration.

For disability/accessibility studies, recruitment criteria and any health/disability information
require much more deliberate ethics/privacy handling. Do not ask public GitHub testers for diagnosis.

## Paper-quality provenance

Reuse/extend the existing benchmark provenance:
- commit/version;
- command/protocol version;
- dependency versions;
- CPU/RAM/OS;
- system load for timing;
- camera capture mode;
- display topology;
- model asset version;
- relevant config hash.

Add:
- evaluation schema version;
- task set/version;
- research protocol ID/version;
- analysis version.

## Statistical/reporting principles

Before main data collection:
- declare primary outcomes;
- declare exclusions;
- declare aggregation unit;
- declare comparisons;
- declare whether analyses are exploratory/confirmatory.

For repeated trials:
- report participant-level distributions/intervals;
- do not treat trials as independent participants;
- preserve wrong-target vs fallback distinction;
- report failures/blocked environments.

For cross-machine timing:
- report by host/config; do not average unlike machines into a single latency number.

For false activations:
- report both event count and exposure time; rate/hour requires a denominator.

## What can go in the public paper artifact

Preferred:
- protocol;
- task generator;
- synthetic traces;
- analysis scripts;
- aggregate tables;
- de-identified trial-level data only if ethics/consent permits and re-identification risk is
  acceptable;
- machine provenance stripped of host/user identifiers.

Do not release:
- names/emails/GitHub usernames;
- consent forms;
- raw face video/images;
- private desktop recordings;
- diagnosis/free-text health information.

## Data-quality rules

Every research row carries:
- schema version;
- source type;
- protocol version;
- participant/session/trial ID;
- validity;
- exclusion reason if excluded.

No spreadsheet hand-edits without an auditable transformation script.

Raw captured research artifact (if any) is immutable/restricted; analysis datasets are generated,
versioned derivatives.

## Community reports and the paper

Default:
**do not put public QA reports into the participant dataset.**

They can support:
- bug discovery;
- platform coverage;
- qualitative engineering observations;
- motivation for a later study.

If a community tester volunteers for the research study, collect a new research session under the
research protocol instead of retroactively treating their GitHub issue as consent.

## Ethics/publication gate

Before human-participant data intended for an ACM-style HCI publication:
- follow the authors' institutional/local ethics requirements;
- retain documentation of the determination/approval;
- use informed consent;
- disclose the review/ethics context in the manuscript as required by the venue;
- tell participants about data sharing/publication.

This is a **pre-data-collection gate**, not a manuscript-writing cleanup task.

## Paper-ready definition

The eye-control evidence is paper-ready only when:

- protocol frozen/versioned;
- ethics determination documented;
- participant information/consent finalized;
- instrumentation tested with pilot;
- result schema validated automatically;
- main dataset collected under that protocol;
- exclusions logged;
- analysis is reproducible from de-identified derived data;
- claims in paper map directly to a metric/protocol/table;
- no claim is based on community QA data that was not research-authorized.

