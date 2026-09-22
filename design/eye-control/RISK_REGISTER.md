# Eye / camera control risk register

Risk is tracked separately from implementation because a technically correct camera feature can still
be unusable or unsafe as an accessibility control.

Scales:
- **Impact:** L / M / H / Critical
- **Likelihood:** Low / Medium / High
- **State:** open / mitigated / accepted / deferred

| ID | Risk | Impact | Likelihood | Mitigation / evidence needed | Tracking |
|---|---|---:|---:|---|---|
| R-01 | Gaze selects the wrong window | H | Medium | confidence fallback; destructive confirmation; field wrong-target rate | #104, #399 |
| R-02 | Calibration silently invalid after monitor/layout/scale/camera change | H | High | topology fingerprint + explicit invalidation/revalidation | ADR-v2-139 + #415 |
| R-03 | Face switch fires without deliberate intent | H | Medium | hysteresis, hold, refractory, confidence; false activations/hour | #406, #409 |
| R-04 | Head pointer accidentally clicks | H | Medium | dwell progress, pause/clutch, re-arm rule, watchdog | #405 + #417 |
| R-05 | User cannot stop continuous camera control | Critical | Low/Medium | global pause/kill path independent of the controlled pointer | #417 |
| R-06 | Stale last pose causes repeated movement after tracking loss | H | Medium | timestamp freshness + zero-output watchdog | #404 + #417 |
| R-07 | Two features fight over webcam | H | High without ADR-135 | single camera owner + subscriber lifecycle | #394 |
| R-08 | Camera busy/permission denied breaks ordinary dictation | H | Medium | failure isolation; doctor/status; no-camera fallback | #414 + #416 |
| R-09 | Raw face data leaks to log/disk/report | Critical | Low | derived-signal-only contracts, privacy tests, review | ADR-v2-135, test plan |
| R-10 | Model download unexpectedly uses network | M | Medium on first use | explicit model lifecycle; status; existing download policy | #414 |
| R-11 | Continuous FaceLandmarker causes excessive CPU/battery | M | Medium | FPS cap, one inference, measure CPU/FPS | #395, #411 |
| R-12 | Facial commit moves head pointer at same time | M/H | Medium | freeze pointer during gesture interval | #407 |
| R-13 | Talking itself triggers mouth-open switch | H | Medium/High | calibrated gesture definition; trace + field testing; choose safe defaults | #406, #409 |
| R-14 | Blink mapping conflicts with natural blink | H | High | never default; advanced opt-in; evidence gate | #406 |
| R-15 | Wayland portal pointer works but gaze cannot focus target window | M | High | separate target-semantics design; explicit fallback | #418 |
| R-16 | HiDPI coordinate spaces mismatch | H | Medium | canonical logical/physical coordinate spec + tests | ADR-v2-139 + #415 |
| R-17 | Multi-monitor gaze target crosses wrong display | H | Medium | per-display geometry and topology-bound calibration | ADR-v2-139 + #415 |
| R-18 | Accessibility defaults cause fatigue/neck strain | H | Unknown | adjustable gain/deadzone/dwell; user study; no recommendation without review | #411 + #419 |
| R-19 | Camera indicator/active state is not visible | M | Medium | status/tray/doctor observability | #416 |
| R-20 | Optional camera deps break base install | H | Low/Medium | lazy imports/extras, default-install CI | #393–#396 |
| R-21 | Packaging declares camera permission when feature is unreachable | M | Existing on some bundles | permission capability matches shipped extras | #392 + #414 |
| R-22 | Dedicated tracker SDK imposes incompatible license/runtime | H | Unknown | licensing/API study before dependency | #412 |
| R-23 | User's face characteristics/lighting materially change detector reliability | H | High | per-user neutral calibration + heterogeneous field evidence | #406, #411 |
| R-24 | Error recovery itself triggers an action | H | Low/Medium | recovery returns to paused/neutral state; explicit re-arm | #417 |
| R-25 | Correct window but wrong semantic control is grounded | H | Medium | ambiguity/abstention policy; wrong-target harness | #442, #445 |
| R-26 | Accessibility tree is missing, stale or exposes unusable bounds/actions | M/H | High/Unknown by app | live coverage study; explicit unresolved fallback | #444 |
| R-27 | Voice label/role hint overrides spatial evidence and selects an off-region element | H | Low/Medium | invariant: hint refines plausible set only; regression fixtures | #442 |
| R-28 | Future OCR/VLM fallback captures private screen content or adds egress/dependency cost | Critical | Unknown | explicitly deferred; separate ADR/privacy/egress review required | deferred — no implementation issue |
| R-29 | Target confidence is mistaken for permission to execute a risky action | H | Medium | grounding never executes; keep action risk/confirmation downstream | ADR-v2-141 + #443 |

## Release blockers

The following remain **release blockers for the hands-free bundle**, even if unit tests are green:

- R-05 global stop/kill behavior unresolved;
- R-08 permissions/failure isolation unresolved;
- R-09 any raw-frame persistence/egress;
- R-16/R-17 coordinate-space ambiguity;
- R-24 re-arm behavior after sensor failure.

## Recommendation blockers

The following block experimental -> recommended promotion:

- no measured R-03 face false-activation rate;
- no measured R-04 accidental-click rate;
- no R-18 usability/fatigue evidence;
- only one camera/environment tested;
- defaults derived solely from one developer's setup.

### Grounded-target promotion blockers

Exact-element grounding must remain experimental until:

- #444 has real multi-platform semantic-source evidence;
- #445 reports wrong-target and abstention separately;
- R-25/R-27 have deterministic regression coverage;
- no implementation has introduced the deferred R-28 screenshot/VLM path without a new ADR;
- action confirmation remains independent from resolution confidence.

## Updating this register

A PR that discovers a new material failure mode should add it here even if the PR fixes it. Record
the risk and mark it mitigated with the test/evidence link; future implementations need to know why
the guard exists.
