# Eye / camera control metrics dictionary

This file is the canonical name/meaning list for machine-readable evaluation results. A metric name
must mean the same thing on Windows, macOS and Linux.

The evaluation harness should reuse the provenance principles already used by
`paper/benchmark/_common.py`: a number without the machine/software/config that produced it is not
a reproducible measurement.

## Result envelope

Every result artifact should contain:

```text
schema_version
study_mode
timestamp
software
machine
os_session
display
camera
feature
config
protocol
metrics
privacy
```

No field contains a face image, raw video, transcript, window title, username, home path or email.

## Study mode

Required enum:

- `ci` — automated CI;
- `synthetic` — deterministic generated/replayed trace;
- `community_qa` — public engineering test, **not research-use by default**;
- `research` — collected under a named research protocol/ethics/consent process.

This field prevents a future analysis script from accidentally mixing QA with human-study data.

## Software provenance

Required:
- YazSes version;
- git commit SHA when available;
- Python version;
- perception backend/model/version;
- relevant package versions;
- schema version;
- result-generator version/command.

Prefer a **config hash** plus a whitelist of relevant non-sensitive feature settings.

Do not dump the entire user config.

## Machine provenance

Collect automatically where possible:

- OS name/version;
- kernel/build;
- architecture;
- CPU model;
- logical CPU count;
- RAM GB;
- session/compositor: X11 / GNOME Wayland / KDE Wayland / Windows / macOS;
- system load at start/end for performance runs.

Do **not** collect:
- hostname;
- login username;
- serial number;
- MAC address;
- full device UUID.

## Display provenance

Required when gaze/pointer coordinates matter:

- display count;
- each display logical rectangle;
- resolution;
- scale factor;
- primary display indicator;
- topology fingerprint (pseudonymous/hash of non-secret geometry fields).

Optional for paper/user-entered:
- physical diagonal/width;
- approximate viewing distance.

Physical dimensions + viewing distance are needed only when converting pixels to angular error.
Do not require them for ordinary QA.

## Camera provenance

Collect:
- backend/device label sanitized to model/product class where possible;
- integrated vs external;
- capture width/height;
- nominal/measured FPS;
- selected camera index only as local configuration, not a stable identity;
- model/FaceLandmarker asset version.

Do not collect:
- camera serial number;
- USB serial;
- a photo/frame;
- raw face landmarks by default.

## Runtime/performance

Recommended:
- source FPS median / P5;
- dropped/invalid sample rate;
- frame-to-derived-signal latency P50/P95 if measurable;
- derived-signal age at action P50/P95;
- CPU process utilization;
- RSS delta;
- number of physical camera opens;
- permission/startup time where relevant.

Interpret performance per machine. Do not average latency across unlike hosts into one "YazSes
latency".

## Gaze metrics

Counts:
- `trials`;
- `correct_target`;
- `wrong_target`;
- `fallback_no_route`;
- `invalid_tracking`.

Rates:
- correct-target rate;
- wrong-target rate;
- fallback rate.

Calibration:
- explicit calibration points;
- calibration/validation RMSE px;
- held-out RMSE px;
- optional angular error degrees **only** when display geometry + viewing distance are available;
- calibration age/time since fit;
- implicit sample count;
- candidate-vs-baseline delta;
- topology valid/stale.

Session:
- error by time block to quantify drift;
- reacquisition time after tracking loss.

Never report one generic "gaze accuracy %" without defining whether it means coordinate error,
correct-window rate, or tracker availability.

## Head-Pointer metrics

Per target/trial:
- success;
- movement time ms;
- target distance/amplitude;
- target width;
- miss count;
- overshoot/correction count if instrumented;
- accidental click;
- tracking-loss count/duration;
- pause count;
- recenter count.

Aggregate:
- task completion rate;
- median/P95 movement time;
- miss rate;
- accidental clicks/hour;
- optional effective pointing throughput under a preregistered analysis.

Do not infer motor ability or medical condition from these numbers.

## Face-switch metrics

Per block:
- gesture;
- intended activations;
- detections;
- misses;
- false/extra activations;
- duration seconds;
- activation latency distribution;
- configured enter/exit thresholds;
- hold duration;
- refractory interval;
- confidence threshold.

Primary aggregate:
- false activations/hour;
- recall/intent detection rate;
- median activation latency.

Keep neutral and normal-speaking blocks separately identifiable.

## Semantic grounding metrics

Use for #441–#445 and any future "look at this field/button/item" refinement.

Per trial:
- target source and coarse target ID (synthetic/non-sensitive);
- eligible semantic candidate count;
- candidates with usable bounds;
- actionable candidate count;
- candidates spatially plausible after coarse-target filtering;
- optional candidate count after an intent/role hint;
- result state: `grounded`, `ambiguous`, `unresolved`;
- correctness when ground truth is available: `correct` / `wrong`;
- stale/coordinate-space-mismatch reason where applicable;
- resolver latency when performance is being studied.

Aggregate:
- grounded-correct rate;
- grounded-wrong rate;
- ambiguity rate;
- unresolved/abstention rate;
- semantic coverage (targets with at least one usable candidate);
- actionable coverage;
- candidate-count distribution before/after spatial filtering;
- candidate-count distribution after optional intent hint.

Safety rule:
**wrong target and abstention are not the same error.** A resolver that declines an ambiguous target
may be safer than one that always returns an element.

Do not store private UI text, screenshots, raw accessibility objects, email/document content or
window titles containing personal information. Controlled task fixtures should use synthetic labels.

## Hands-free workflow metrics

- task completion yes/no;
- total completion time;
- unintended action count;
- recovery action count;
- fallback modality count/type;
- keyboard/mouse intervention required yes/no;
- pause/kill successfully invoked yes/no;
- recover-from-camera-loss success yes/no.

Research-only subjective measures may include participant-reported:
- ease/confidence;
- comfort;
- fatigue/change over session;
- preference.

Use a frozen questionnaire/scale in the study protocol; community QA should keep subjective questions
short and optional.

## Human-study identifiers

Research datasets need linkage without identity.

Use:
- random `participant_id` assigned by the study;
- `session_id`;
- trial number.

Do not put GitHub username, email or real name in the analysis dataset.

The consent/contact record, if required, is stored separately from measurements with access limited
to the research team.

## Missing data

Use explicit missing/null + reason:
- not supported;
- not measured;
- permission denied;
- tracking unavailable;
- participant stopped;
- technical invalidation.

Do not encode missing as zero.

## Exclusions

Any result excluded from analysis must retain:
- exclusion reason;
- whether exclusion was technical/protocol/user withdrawal;
- whether exclusion rule was defined before analysis.

Never delete poor performance merely because it is inconvenient.

