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
run
metrics
privacy
```

`run` is written by the evaluation runner (verdict, completeness and blocked reason); the schema
does not require it. The other thirteen are the envelope proper.

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

## Emitted keys

This is the machine-checked list of every name the programme's code can write. The names in the
sections above are prose; the names below are the ones that appear in a result file or a replay
report, so an analysis script and a reviewer read the same word.
`tests/test_eye_acceptance_consistency.py` derives the emitted set from the code
(`yazses.eyeeval.runner.tally`, `build_result`, and the committed grounding replay report) and fails
when this table and the code disagree in either direction: a key the code can write that is not listed
here, or a key listed here that the code no longer writes.

The unit is part of the name, never a separate field: `_ms` milliseconds, `_s` seconds, `_rate` and
`_share_` a fraction in `[0, 1]`, `_per_hour` events per hour of the scored exposure, and no suffix a
whole-number count. A median is `_p50`; a total across trials is `_total`. A key that could not be
measured is `{"value": null, "reason": ...}`, never `0` (see "Missing data").

| Emitter | Key | Unit | Meaning |
|---|---|---|---|
| `gaze_routing_4_pane` | `trials` | count | scored trials recorded |
| `gaze_routing_4_pane` | `correct_target` | count | trials routed to the intended pane |
| `gaze_routing_4_pane` | `wrong_target` | count | trials routed to another pane |
| `gaze_routing_4_pane` | `fallback_no_route` | count | trials where gaze declined to route (the safe outcome; never merged into wrong target) |
| `gaze_routing_4_pane` | `invalid_tracking` | count | trials with no usable tracking |
| `gaze_routing_4_pane` | `correct_target_rate` | fraction | `correct_target` over scored trials |
| `gaze_routing_4_pane` | `trial_time_ms_p50` | ms | median trial time |
| `gaze_routing_4_pane` | `calibration_age_s_p50` | s | median time since the calibration fit |
| `head_pointer_generated_targets` | `trials` | count | scored target trials recorded |
| `head_pointer_generated_targets` | `hit` | count | trials recorded with outcome `hit` |
| `head_pointer_generated_targets` | `miss` | count | trials recorded with outcome `miss` |
| `head_pointer_generated_targets` | `abandoned` | count | trials recorded with outcome `abandoned` |
| `head_pointer_generated_targets` | `tracking_lost` | count | trials recorded with outcome `tracking_lost` |
| `head_pointer_generated_targets` | `completion_rate` | fraction | `hit` over scored trials |
| `head_pointer_generated_targets` | `movement_time_ms_p50` | ms | median movement time (the P95 is not emitted; see below) |
| `head_pointer_generated_targets` | `miss_count_total` | count | misses across all trials |
| `head_pointer_generated_targets` | `recenter_count_total` | count | recenters across all trials |
| `head_pointer_generated_targets` | `tracking_loss_ms_total` | ms | time with no usable tracking |
| `head_pointer_generated_targets` | `accidental_click_count_total` | count | clicks nobody asked for (a total; a per-hour rate needs an exposure this task does not emit) |
| `face_switch_blocks` | `cues` | count | scored cue records across the neutral, deliberate and speaking blocks |
| `face_switch_blocks` | `detected` | count | records with outcome `detected` |
| `face_switch_blocks` | `missed` | count | records with outcome `missed` |
| `face_switch_blocks` | `false_activation` | count | records with outcome `false_activation` |
| `face_switch_blocks` | `detection_rate` | fraction | `detected` over `cues` |
| `face_switch_blocks` | `activation_latency_ms_p50` | ms | median cue-to-activation latency |
| `face_switch_blocks` | `false_activation_count_total` | count | extra activations across all blocks |
| `face_switch_blocks` | `scored_duration_s` | s | exposure: scored seconds the false-activation count was observed over |
| `face_switch_blocks` | `false_activations_per_hour` | per hour | `false_activation_count_total` over the scored exposure |
| `run` | `verdict` | enum | `PASS`, `PARTIAL`, `FAIL` or `BLOCKED`; completeness of the protocol, never accuracy |
| `run` | `completeness_verdict` | enum | the verdict the code computed |
| `run` | `verdict_source` | enum | `tester` or `computed` |
| `run` | `verdict_definition` | text | what the verdict does and does not say |
| `run` | `records_source` | text | where the trial records came from |
| `run` | `scored_trials_expected` | count | trials the task asks for |
| `run` | `scored_trials_recorded` | count | trials actually recorded |
| `run` | `blocked_reason` | enum | a missing-data reason when `BLOCKED`, else null |
| `grounding_replay` | `total_trials` | count | replayed cases |
| `grounding_replay` | `grounded_correct` | count | resolved to the intended element |
| `grounding_replay` | `grounded_wrong` | count | resolved to a different element |
| `grounding_replay` | `ambiguous` | count | declined: two plausible elements |
| `grounding_replay` | `unresolved` | count | declined: no usable element |
| `grounding_replay` | `grounded_wrong_containing_expected` | count | wrong, but the right element lay inside the chosen region |
| `grounding_replay` | `grounded_correct_rate` | fraction | `grounded_correct` over all trials |
| `grounding_replay` | `wrong_target_rate` | fraction | `grounded_wrong` over all trials |
| `grounding_replay` | `ambiguity_rate` | fraction | `ambiguous` over all trials |
| `grounding_replay` | `unresolved_rate` | fraction | `unresolved` over all trials |
| `grounding_replay` | `abstention_rate` | fraction | ambiguous plus unresolved over all trials |
| `grounding_replay` | `grounded_correct_share_of_grounded` | fraction | correct among the trials that resolved at all |
| `grounding_replay` | `grounded_wrong_by_source` | group | wrong-target count by target source |
| `grounding_replay` | `abstention_sources` | group | why a trial abstained |
| `grounding_replay` | `candidate_counts` | group | candidate-count histogram before and after an intent hint |

The grounding replay report is its own document (`report_version`), not an `eyeeval` result, and
`yazses.eyeeval.schema` does not validate it. Its names are listed here so the two vocabularies are
read side by side: `wrong_target_rate` there and `wrong_target` here are different quantities (a rate
over all trials versus a gaze count) and must not be merged.

## Defined, not yet emitted

The protocol in [VALIDATION_MATRIX.md](VALIDATION_MATRIX.md) asks for more than the code can yet
write. These keys are defined so a hand-filled or future-emitted value has one agreed name and
unit. **No runner, task fixture or schema check produces any of them today**; the test fails if one
of them appears in the emitted set without leaving this table, so the table cannot quietly keep
claiming a gap that has been closed.

| Key | Unit | Meaning | Needed by |
|---|---|---|---|
| `start_result` | enum | `pass`, `fail` or `blocked` for starting the feature | T0 |
| `stop_result` | enum | `pass`, `fail` or `blocked` for stopping it and releasing the camera | T0 |
| `permission_result` | enum | `granted`, `denied` or `not_asked` | T0 |
| `camera_open_count` | count | physical camera opens, where instrumented | T0 |
| `calibration_validation_rmse_px` | px | validation error of the fitted calibration | T1 |
| `error_by_time_block` | group | wrong-target and fallback counts per time block, to show drift | T1 |
| `overshoot_count_total` | count | pointer overshoot/correction events | T2 |
| `pause_count_total` | count | times the controls were paused during the block | T2 |
| `exposure_s` | s | scored seconds of Head-Pointer exposure (the denominator of any per-hour rate) | T2 |
| `miss_rate` | fraction | misses over scored trials | T2 |
| `movement_time_ms_p95` | ms | 95th-percentile movement time | T2 |
| `accidental_clicks_per_hour` | per hour | accidental clicks over `exposure_s` | T2 |
| `intended_activation_count` | count | cues in the deliberate block only (`cues` also counts neutral and speaking records, so it is not this) | T3 |
| `stale_motion_after_loss_count` | count | pointer motion after tracking was lost (PASS needs 0) | T4 |
| `repeated_switch_event_count` | count | switch events repeated after recovery (PASS needs 0) | T4 |
| `dwell_click_on_recovery_count` | count | dwell clicks immediately after recovery (PASS needs 0) | T4 |
| `independent_stop_path_works` | boolean | a stop path that does not use the controlled pointer worked | T4 |
| `calibration_topology_transition` | enum | `none`, `valid_to_stale` or `stale_to_valid` | T5 |
| `wrong_display_count` | count | trials resolved on the wrong display | T5 |
| `routing_suspended_on_incompatible_topology` | boolean | routing stopped when the topology no longer matched the calibration | T5 |
| `candidates_in_region_count` | count | semantic candidates inside the coarse region | T6 |
| `candidates_with_bounds_count` | count | candidates with usable bounds | T6 |
| `actionable_candidate_count` | count | candidates that expose an action | T6 |
| `hands_free_task_completed` | boolean | the whole workflow finished | T7 |
| `hands_free_total_time_s` | s | workflow wall time | T7 |
| `unintended_action_count` | count | actions nobody asked for | T7 |
| `recovery_action_count` | count | recoveries the participant performed | T7 |
| `fallback_modality_count` | count | times another modality was used instead | T7 |
| `keyboard_mouse_intervention` | boolean | the physical keyboard or mouse was needed | T7 |
| `pause_kill_invoked_ok` | boolean | pause/stop worked when invoked | T7 |
| `camera_loss_recovery_ok` | boolean | recovered from deliberate camera loss | T7 |

## Protocol coverage

Every item the packs in [VALIDATION_MATRIX.md](VALIDATION_MATRIX.md) say they will collect, mapped to
the key that carries it. An item with no emitted key is a gap in the code, stated here rather than
discovered by a tester. A pack item added to the matrix without a row here fails the test; so does a row
whose key is in neither table above.

| Pack | Item | Emitted keys | Defined-only keys |
|---|---|---|---|
| T0 | PASS/PARTIAL/FAIL/BLOCKED | `verdict` | — |
| T0 | start/stop result | — | `start_result`, `stop_result` |
| T0 | permission result | — | `permission_result` |
| T0 | camera-open count where instrumented | — | `camera_open_count` |
| T0 | failure reason | `blocked_reason` | — |
| T0 | OS/computer/camera/display provenance | `machine`, `os_session`, `camera`, `display` | — |
| T1 | trials | `trials` | — |
| T1 | correct target | `correct_target` | — |
| T1 | wrong target | `wrong_target` | — |
| T1 | fallback/no-route | `fallback_no_route` | — |
| T1 | invalid tracking | `invalid_tracking` | — |
| T1 | calibration validation error | — | `calibration_validation_rmse_px` |
| T1 | calibration age | `calibration_age_s_p50` | — |
| T1 | result by time block for drift | — | `error_by_time_block` |
| T2 | target success | `hit` | — |
| T2 | movement time | `movement_time_ms_p50` | — |
| T2 | misses/overshoots | `miss_count_total` | `overshoot_count_total` |
| T2 | accidental clicks | `accidental_click_count_total` | — |
| T2 | tracking losses | `tracking_lost`, `tracking_loss_ms_total` | — |
| T2 | pauses | — | `pause_count_total` |
| T2 | recenters | `recenter_count_total` | — |
| T2 | test exposure time | — | `exposure_s` |
| T2 | completion rate | `completion_rate` | — |
| T2 | median/P95 movement time | `movement_time_ms_p50` | `movement_time_ms_p95` |
| T2 | miss rate | — | `miss_rate` |
| T2 | accidental clicks/hour | — | `accidental_clicks_per_hour` |
| T3 | intended activations | — | `intended_activation_count` |
| T3 | detections | `detected` | — |
| T3 | misses | `missed` | — |
| T3 | false activations | `false_activation`, `false_activation_count_total` | — |
| T3 | exposure seconds/minutes | `scored_duration_s` | — |
| T3 | activation latency | `activation_latency_ms_p50` | — |
| T3 | gesture + threshold/hold/refractory configuration | `config` | — |
| T4 | no stale pointer movement | — | `stale_motion_after_loss_count` |
| T4 | no repeated switch event | — | `repeated_switch_event_count` |
| T4 | no immediate dwell click on recovery | — | `dwell_click_on_recovery_count` |
| T4 | an independent stop path works | — | `independent_stop_path_works` |
| T5 | topology fingerprint | `display` | — |
| T5 | calibration valid/stale transition | — | `calibration_topology_transition` |
| T5 | wrong-display result | — | `wrong_display_count` |
| T5 | whether routing suspends when topology becomes incompatible | — | `routing_suspended_on_incompatible_topology` |
| T6 | candidates in coarse region | — | `candidates_in_region_count` |
| T6 | candidates with usable bounds | — | `candidates_with_bounds_count` |
| T6 | actionable candidates | — | `actionable_candidate_count` |
| T6 | grounded-correct | `grounded_correct` | — |
| T6 | grounded-wrong | `grounded_wrong` | — |
| T6 | ambiguous | `ambiguous` | — |
| T6 | unresolved/abstained | `unresolved` | — |
| T6 | candidate count before/after optional intent hint | `candidate_counts` | — |
| T6 | wrong-target rate | `wrong_target_rate` | — |
| T6 | ambiguity rate | `ambiguity_rate` | — |
| T6 | abstention rate | `abstention_rate` | — |
| T7 | task completed | — | `hands_free_task_completed` |
| T7 | total time | — | `hands_free_total_time_s` |
| T7 | unintended actions | — | `unintended_action_count` |
| T7 | recoveries | — | `recovery_action_count` |
| T7 | fallbacks | — | `fallback_modality_count` |
| T7 | keyboard/mouse intervention | — | `keyboard_mouse_intervention` |
| T7 | stop/pause success | — | `pause_kill_invoked_ok` |

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

