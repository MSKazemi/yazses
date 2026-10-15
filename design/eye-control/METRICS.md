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

### Gaze field-measurement report (`yazses gaze measure`, #399)

The report a tester attaches to #104. Envelope as above; `feature.name = "gaze"`,
`protocol.task = "gaze_field_measurement"`, `protocol.task_version = "1.1"`. The authoritative
list is `REQUIRED_METRICS` in `src/yazses/eyeeval/gaze_field.py`, which the validator enforces; a
golden file (`tests/fixtures/gaze_field_report/full_session.json`) pins the whole document.

| Group | Keys | Notes |
|---|---|---|
| `calibration` | `source`, `age_s`, `topology_validity`, `validation_points`, `error_px_rmse`, `error_px_mean`, `error_px_max`, `error_deg_mean`, `implicit_candidate_delta_px` | Coordinate error. Degrees only with screen size and viewing distance. `topology_validity` is `unverified` when the layout could not be re-read after the pass; a layout that changed during the pass writes no report. |
| `confidence` | `samples`, `mean`, `min`, `max`, `below_threshold_fraction`, `threshold`, `histogram` | Availability/quality signal; a ten-bin histogram, never a time series. A backend that reports no per-sample confidence (L2CS) gives `reason: not_supported`, not a value. |
| `routing` | `attempts`, `gaze_routed`, `fallback_no_route`, `wrong_target_corrections`, `wrong_target_rate`, `fallback_rate` | Window-level outcome, tester-counted; missing when not counted. |
| `session` | `duration_s`, `block_s`, `drift_blocks` | Mean error per time block; blocks with no point are omitted, not zero. |
| `environment` | `glasses`, `lighting`, `viewing_distance_cm`, `camera_label` | Volunteered; `not_stated` when omitted. |
| `sufficiency` | `provisional`, `validation_points`, `confidence_samples`, `routing_attempts`, `drift_blocks` (each `{n, minimum, enough}`), `statements` | Says in the document when there is too little data to mean anything. The minimums are **provisional reporting floors** (5 points, 30 confidence samples, 20 routing attempts, 2 time blocks): they stop a one-point report reading as a finding and are not a power calculation. Unmeasured, to be revised with field evidence (#104). |

Never exported: frames, face meshes or landmarks, screenshots, dictated or typed text, window
titles, identity. There is no field for any of them, and the document is swept for home paths,
e-mail addresses and the machine's own hostname and login before it is written.

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

## Schema versioning and compatibility

The envelope above is implemented by `yazses.eyeeval.schema`, which validates a parsed
result document and returns a list of problems. `schema_version` is `"MAJOR.MINOR"`.

- **Same MAJOR — accepted.** Unknown fields, at any depth, are *ignored and preserved*,
  never an error. A later minor version may add a field and an older reader still works,
  so a reader must not assume the keys it knows are all the keys present.
- **Different MAJOR — refused.** A major bump means a required field was removed or its
  meaning changed; reading it anyway would produce a number that silently means something
  else.

So: add a field, bump the minor. Change or remove one, bump the major.

A later minor is accepted **with a note**, not silently: `compatibility_note` says fields
added since the reader's version were not checked, and the checker prints it.

Check a result file — yours or an attachment from someone else — with:

```bash
uv run python scripts/check_eye_eval_result.py result.json
```

Exit `0` if every file is valid, `1` if any is invalid, `2` if no file was named. A missing,
empty, non-UTF-8, non-JSON or `NaN`-carrying file, or one that repeats a key, is reported as
invalid rather than read as an empty document.

Inside `metrics`, an object carrying `value` or `reason` is a missing-data marker (below)
and never a metric group, so a metric group may not have a member called `value`. A marker
is either measured (`value`, no `reason`) or missing (`value: null` plus a `reason`), never
both; an empty metric group, a bare `null` inside a list, and a non-finite number (`NaN`,
infinity) are refused for the same reason a bare `null` is.

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

