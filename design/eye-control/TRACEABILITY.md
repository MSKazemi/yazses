# Eye / camera control traceability matrix

This is the one-page map from **decision -> spec -> issue -> verification**.

## Core architecture

| Area | Decision | Spec | Implementation issues | Evidence / gate |
|---|---|---|---|---|
| Gaze routes context, not caret | ADR-v2-010 | `design/specs/glance-type.md` | existing live code + #397–#399 | gaze routing tests + #104 |
| Shared webcam/model owner | ADR-v2-145 | `design/specs/eye-shared-perception.md` | #393–#396 | one-open lifecycle tests |
| Pointer output boundary | ADR-v2-146 | `design/specs/eye-pointer-output.md` | #400–#403 | shared sink contract + platform smoke |
| Head-Pointer runtime | ADR-v2-052 + ADR-v2-146 | `design/specs/eye-head-pointer-runtime.md` | #404–#405 | fake trace + hardware acceptance |
| Face gesture is a switch | ADR-v2-147 | `design/specs/eye-face-switch.md` | #406–#409 | false activations/hour |
| Gesture composition | ADR-v2-043 + ADR-v2-147 | `design/specs/eye-face-switch.md` | #408 | chord resolver tests |
| Hands-free is composition | ADR-v2-148 | `design/specs/eye-handsfree-bundle.md` | #410 + #416 + #417 | end-to-end scenario |
| Calibration topology | ADR-v2-149 | `design/specs/eye-implicit-calibration.md` | #397–#398 + #415 | invalidation/rollback tests |
| Dedicated tracker seam | future ADR only if study warrants | [DEDICATED_TRACKER_STUDY.md](DEDICATED_TRACKER_STUDY.md) (research note, no implementation) | #412 | API/licensing study |
| Grounded semantic targets | ADR-v2-151 (Proposed) | `design/specs/eye-grounded-targets.md` | #441–#445 | pure resolver + semantic coverage + wrong-target/abstention |

## Cross-cutting implementation gaps

The original #392–#412 split covered the feature path but not all production obligations. The
programme also tracks:

| Gap | Why it is separate | Required result |
|---|---|---|
| Camera permissions + packaging | OS/package permissions can make correct code unreachable | #414 — explicit permission matrix + package behavior |
| Multi-monitor/HiDPI/topology | gaze coordinates and calibration can silently become wrong | #415 — canonical coordinate space + invalidation |
| Observability | assistive sensor failure must be diagnosable without logs full of biometric detail | #416 — `doctor`/status state |
| Global pause/kill/watchdog | continuous pointer/switch input needs an immediate escape | #417 — one safety control across consumers |
| Wayland gaze target semantics | pointer portal does not automatically solve "which window receives dictation" | #418 — documented supported/fallback behavior |
| Accessibility co-design | synthetic tests do not establish usability/fatigue/defaults | #419 — structured review protocol + evidence |

These gaps receive dedicated issues in milestone #10.

## Dependency graph

```text
DESIGN / GOVERNANCE
  ADR-v2-145 shared perception
      |
      +--> #393 signal contracts
            -> #394 source lifecycle
            -> #395 multi-signal MediaPipe
            -> #396 migrate gaze
                  +-> #397 click capture -> #398 safe apply
                  +-> #399 measurement
                  +-> Wayland target semantics
                  +-> topology/HiDPI validation

  ADR-v2-146 pointer boundary
      |
      +--> #400 PointerSink
            +-> #401 X11
            +-> #402 macOS/Windows
            +-> #403 Wayland portal
                    |
                    +----> #404 Head-Pointer runtime -> #405 UX/recovery

  ADR-v2-147 face-switch intent
      |
      +--> #406 detector -> #407 activation adapter
                              +-> #408 Gesture Chords
                              +-> #409 false-activation harness

  permission + observability + global safety
                   \            |             /
                    +----------- #410 hands-free bundle
                                      |
                                    #411 field acceptance
                                      |
                                    #419 co-design
                                      |
                           experimental -> recommendation gate

  ADR-v2-151 grounded target resolution
      |
      +--> #441 contracts
            -> #442 pure resolver
                 +-> #443 gaze/deixis integration
                 +-> #445 evaluation harness
      |
      +--> #444 live semantic-source coverage (human/platform evidence)

  #412 dedicated tracker study is parallel/future
```

## Status rules

When code lands, update **all** of:
- this matrix;
- `README.md` status table;
- relevant spec status;
- `docs/features.md`;
- feature registry wiring status when applicable;
- issue state.

A merge that updates code but leaves a capability listed as DESIGNED/CORE is incomplete planning
work.

## Verification ownership

| Verification | Runs in CI? | Needs human/device? |
|---|---|---|
| Pure detector/state machine | yes | no |
| Fake MediaPipe adapter | yes | no |
| Pointer protocol contract | yes | no |
| Portal D-Bus protocol fake | yes | no |
| Feature reachability | yes | no |
| No-camera when disabled | yes | no |
| No raw-frame persistence | yes/static | no |
| Camera permission prompt | no | yes |
| Real pointer movement | no | yes |
| False activation/hour | harness yes; measurement no | yes |
| Fatigue/usability | no | yes |
| Cross-device recommendation | no | multiple humans/devices |

## Release proof bundle

Before an experimental release, one issue/PR should be able to link:
1. merged ADR/spec;
2. implementation PR;
3. narrow CI;
4. privacy/permission result;
5. at least one hardware report;
6. setup/troubleshooting docs.

Before recommended status, add:
7. multi-environment field evidence;
8. false-activation/error metrics;
9. accessibility review;
10. resolved/accepted risk register.


## Evaluation traceability

| Evidence need | Contract | Issues | Output |
|---|---|---|---|
| Metric/result semantics | `METRICS.md` | #421 | versioned result schema |
| Standard non-sensitive tasks | `EVALUATION.md` | #422 | deterministic task fixtures |
| Local privacy-safe capture | `DATA_SHARING.md` | #423 | local validated JSON |
| Cross-OS automated evidence | E0–E2 | #424 | CI artifacts |
| Cross-machine hardware QA | E3/E4 | #428–#436 + #438–#440 | public community QA reports |
| Test-retest stability | E6 | #437 | 3 session artifacts |
| Human-study design/ethics | `PAPER_EVIDENCE.md` | #425 | frozen protocol + determination |
| Research analysis | `METRICS.md` | #426 | reproducible tables/figures |
| Tester/participant wording | `DATA_SHARING.md` | #427 | reviewed public/research materials |
| Beginner instruction usability | `BEGINNER_TESTING.md` | #449 | first-time-reader review |
| Slot readiness / matrix registry | `VALIDATION_OPERATIONS.md` | #454 | validated PLANNED/READY registry |
| Coverage dashboard | `VALIDATION_OPERATIONS.md` | #455 | generated engineering coverage view |
| Contributor task-finder integration | campaign inventory contract | #456 | READY eye slots discoverable as no-code measurement tasks |

Community QA rows are not automatically eligible for participant-level paper analysis.


## Acceptance traceability — #411 and #419

The two human-study issues each carry an acceptance list. This table links every item to its
issue, the validation slots that will collect it, and the pure test that guards what can be guarded
without a person. It records **links, not outcomes**: no row says an item has been met, because for
the "needs a person" column that is not something a repository file can say
([README.md](README.md) explains why this directory keeps no status snapshot). A test checks that
every slot id, test and criterion named here still exists; a dash means there is none yet, and the
test accepts a dash only because `tests/test_eye_acceptance_consistency.py` also checks the row has an
issue.

`T0-*` and similar in the slots column is a glob over the ids in
[`validation-slots.json`](validation-slots.json); it must match at least one.

| ID | Acceptance item | Issue | Registry slots | Pure test | Needs a person |
|---|---|---|---|---|---|
| H1 | Per environment: OS/session, camera, lighting, display/scale, viewing distance, feature config, duration, failures, CPU/FPS, privacy check | #411 | `T0-*` | `tests/test_eye_acceptance_consistency.py::test_every_field_the_test_plan_asks_a_tester_to_report_has_a_form_field` | yes |
| H2 | Gaze wrong-window, fallback and drift | #411 | `T1-*` | `tests/test_eye_acceptance_consistency.py::test_the_emitted_keys_are_documented_with_their_units_and_the_protocol_maps_onto_them` | yes |
| H3 | Head-Pointer overshoot and accidental clicks | #411 | — | `tests/test_headpointer_controller.py::test_a_stale_sample_never_moves_the_pointer_again` | yes |
| H4 | Face-switch misses and false activations per hour | #411 | — | `tests/test_face_switch_replay.py::test_speech_and_everyday_movement_do_not_fire_the_default` | yes |
| H5 | Wayland portal consent and recovery | #411 | `T0-GNOME-*`, `T0-KDE-*` | `tests/test_pointer_consent.py::test_before_the_dialog_is_answered_the_sink_says_pending_and_negotiates_nothing` | yes |
| H6 | Never request face/video, diagnosis, typed content or identity | #411 | `T0-*` | `tests/test_eye_eval_privacy.py::test_the_serialised_document_names_no_forbidden_token` | no |
| H7 | Hardware evidence stays separate from hermetic CI evidence | #411 | — | `tests/test_eye_eval_schema.py::test_community_qa_cannot_declare_itself_research_grade` | no |
| H8 | Replicate each OS and session on two machines (A/B), test/retest | #411 | `T0-*`, `T5-*`, `T1-ANY-REPEAT` | `tests/test_eye_validation_slots.py::test_the_registry_agrees_with_the_prose_matrix_issue_for_issue` | yes |
| H9 | Track FAIL and BLOCKED, not only the machines that worked | #411 | — | `tests/test_eye_validation_dashboard.py::test_a_failed_cell_is_reported_evidence_and_never_missing_evidence` | no |
| H10 | Open later packs only where the capability is reachable | #411 | `T1-*` | `tests/test_eye_acceptance_consistency.py::test_every_cell_the_run_where_table_names_is_registered_or_disclosed_as_a_gap` | no |
| A1 | Start, pause and stop without precise pointer use | #419 | — | `tests/test_handsfree_stopword.py::test_the_match_is_equality_on_the_whole_utterance_not_a_search` | yes |
| A2 | Recover from camera loss | #419 | — | `tests/test_handsfree_e2e_fake_scenario.py::test_the_hands_free_workflow_end_to_end_on_fakes` | yes |
| A3 | Normal speaking does not disturb Head-Pointer or collide with the face switch | #419 | — | `tests/test_face_switch_replay.py::test_speech_and_everyday_movement_do_not_fire_the_default` | yes |
| A4 | How often a false action occurs | #419 | — | `tests/test_eye_acceptance_consistency.py::test_the_emitted_keys_are_documented_with_their_units_and_the_protocol_maps_onto_them` | yes |
| A5 | Dwell time tolerable or frustrating; which fallback is usable | #419 | — | — | yes |
| A6 | Neck and visual fatigue over a session | #419 | — | `tests/test_eye_acceptance_consistency.py::test_the_protocol_requirements_quote_text_that_exists_and_name_only_gaps_that_exist` | yes |
| A7 | Minimum report: completion, errors, duration, before/after comfort rating, own-words comments | #419 | — | `tests/test_eye_acceptance_consistency.py::test_the_protocol_requirements_quote_text_that_exists_and_name_only_gaps_that_exist` | yes |
| A8 | No face/video, no diagnosis, no private content, consent for any quote, negatives kept | #419 | — | `tests/test_eye_eval_privacy.py::test_the_serialised_document_names_no_forbidden_token` | no |
| A9 | Exit: several environments and people, unresolved severe risks documented | #419 | — | `tests/test_eye_validation_slots.py::test_no_slot_is_ready_because_no_slot_has_been_validated_by_a_human` | yes |
| A10 | Report people, sessions, computers, OS/session, cameras, scaling, exposure separately | #419 | — | `tests/test_eye_validation_dashboard.py::test_the_page_states_that_hosts_and_repeat_sessions_are_different_units` | yes |
| A11 | Co-design outside #425 stays out of participant-level analysis | #419 | — | `tests/test_eye_eval_schema.py::test_community_qa_cannot_declare_itself_research_grade` | no |
| A12 | Do not recommend a hands-free default before the evidence | #419 | — | `tests/test_eye_acceptance_consistency.py::test_no_camera_feature_is_on_in_a_default_install` | no |
