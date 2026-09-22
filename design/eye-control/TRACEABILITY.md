# Eye / camera control traceability matrix

This is the one-page map from **decision -> spec -> issue -> verification**.

## Core architecture

| Area | Decision | Spec | Implementation issues | Evidence / gate |
|---|---|---|---|---|
| Gaze routes context, not caret | ADR-v2-010 | `design/specs/glance-type.md` | existing live code + #397–#399 | gaze routing tests + #104 |
| Shared webcam/model owner | ADR-v2-135 | `design/specs/eye-shared-perception.md` | #393–#396 | one-open lifecycle tests |
| Pointer output boundary | ADR-v2-136 | `design/specs/eye-pointer-output.md` | #400–#403 | shared sink contract + platform smoke |
| Head-Pointer runtime | ADR-v2-052 + ADR-v2-136 | `design/specs/eye-head-pointer-runtime.md` | #404–#405 | fake trace + hardware acceptance |
| Face gesture is a switch | ADR-v2-137 | `design/specs/eye-face-switch.md` | #406–#409 | false activations/hour |
| Gesture composition | ADR-v2-043 + ADR-v2-137 | `design/specs/eye-face-switch.md` | #408 | chord resolver tests |
| Hands-free is composition | ADR-v2-138 | `design/specs/eye-handsfree-bundle.md` | #410 + #416 + #417 | end-to-end scenario |
| Calibration topology | ADR-v2-139 | `design/specs/eye-implicit-calibration.md` | #397–#398 + #415 | invalidation/rollback tests |
| Dedicated tracker seam | future ADR only if study warrants | future spec | #412 | API/licensing study |
| Grounded semantic targets | ADR-v2-141 (Proposed) | `design/specs/eye-grounded-targets.md` | #441–#445 | pure resolver + semantic coverage + wrong-target/abstention |

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
  ADR-135 shared perception
      |
      +--> #393 signal contracts
            -> #394 source lifecycle
            -> #395 multi-signal MediaPipe
            -> #396 migrate gaze
                  +-> #397 click capture -> #398 safe apply
                  +-> #399 measurement
                  +-> Wayland target semantics
                  +-> topology/HiDPI validation

  ADR-136 pointer boundary
      |
      +--> #400 PointerSink
            +-> #401 X11
            +-> #402 macOS/Windows
            +-> #403 Wayland portal
                    |
                    +----> #404 Head-Pointer runtime -> #405 UX/recovery

  ADR-137 face-switch intent
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

  ADR-141 grounded target resolution
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

Community QA rows are not automatically eligible for participant-level paper analysis.
