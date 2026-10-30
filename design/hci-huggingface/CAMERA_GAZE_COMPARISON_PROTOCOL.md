# Camera and gaze backend comparison protocol

Status: proposed protocol dated 2026-10-28; **no study has been run and this document contains no
results**. Part of epic #692 / issue #695 (Stage B). No capture source and no change to product
behaviour; the only code is the offline metric script in section 8 and its tests.

It extends the existing eye/camera programme and does not replace it. Metric names, the
evaluation ladder (E0 to E7), the data classes (A to D) and the risk IDs (R-nn) are the ones
defined in `design/eye-control/` (`METRICS.md`, `EVALUATION.md`, `DATA_SHARING.md`,
`RISK_REGISTER.md`); read those first.

## 1. Question

Given the same people, screen and room, how do the camera/gaze backends YazSes already supports
compare on coarse-target selection, abstention, wrong-target error and cost? Optional Hugging Face
checkpoints join the comparison only after they pass the licence and compatibility review in
[model-provenance.md](model-provenance.md) (#694). A checkpoint that is not reviewed is not run.

The comparison supports a **go/no-go decision** about whether to study a backend further. It does
not support a product recommendation: that needs the human co-design work in #419 and the
priorities in ADR-030.

## 2. Candidates

| Candidate | Source | Admission |
|---|---|---|
| Current default backend (`mediapipe`) | shipped | Baseline. Always included. |
| `l2cs` backend (manual install) | shipped, optional | Included when installed. |
| Hugging Face checkpoints named as candidates in the provenance inventory (gaze and face-landmark rows) | Hub, by exact revision | Only after the #694 review marks the licence and compatibility acceptable; consumed through the existing backend interface, outside the product code path. |

Every candidate is recorded by name, exact revision or file hash, licence and the date it was
fetched. "Latest" is never a revision.

## 3. Hard constraints (from the programme, restated because they bind this protocol)

1. **One camera owner.** All candidates read frames through the existing shared perception source
   (ADR-v2-145, risk R-07). No second webcam stack, no second `VideoCapture`.
2. **Derived signals only.** No raw frame, face crop or landmark stream is written to disk, logged
   or attached to an issue (R-09; data Class D is never collected centrally).
3. **No inference beyond gaze.** No emotion, identity, attention, fatigue or health inference from
   the camera, in any candidate or analysis.
4. **No pixel-precision claim.** Gaze is evaluated for coarse targets and voice deixis. No result
   is reported as "accuracy" without saying whether it means coordinate error, correct-window rate
   or availability (`METRICS.md`).
5. **No unexpected network use.** A model is fetched only through an explicit, announced step (R-10).
6. **Feature off means camera unopened.** The comparison harness must not open a camera when the
   feature under test is disabled.

## 4. Where this sits on the evaluation ladder

| Rung | Used here for | Data class |
|---|---|---|
| E2: deterministic synthetic traces | CI checks of the metric code with fake numeric samples and known answers | A |
| E3: one-machine hardware smoke | Confirming the harness runs and the camera opens and closes correctly | A or B |
| E4/E5: cross-computer and cross-person replication | The comparison itself, as engineering validation | B |
| E7: controlled human study | Any claim about people (speed, error across people, comfort) | C |

Claims about people require E7 and its prerequisites (frozen protocol, ethics determination,
informed consent, retention and withdrawal rules) **before** recruitment. Until then the comparison
is engineering evidence and is labelled as such.

## 5. What every session records

Use the existing provenance sections of `METRICS.md` (software, machine, display, camera) and the
`environment` group of the field report (`glasses`, `lighting`, `viewing_distance_cm`,
`camera_label`). Add the following, which the issue requires and which are not recorded today:

| Field | Values |
|---|---|
| Screen geometry | Physical width and height in mm, resolution, scale factor, number of monitors |
| Camera | Frame rate and resolution as negotiated, position relative to the screen |
| Head pose | Self-reported posture category and seating, not a camera-derived measurement |
| OS session | Operating system, compositor or window system (X11 or Wayland), camera permission state |
| Calibration | The ordered list of calibration and validation steps actually performed, and the calibration age at each trial |
| Candidate | Name, exact revision or hash, licence, backend interface used |

An angular error is reported only when display geometry and viewing distance are both recorded
(`METRICS.md`); otherwise the session reports coordinate error only.

## 6. Metrics

| Metric | Definition | Status |
|---|---|---|
| Median and p95 angular gaze error | Per validation point, the angle between the direction to the true target and to the estimated gaze point at the recorded viewing distance; median and 95th percentile over a session, with the point count | **New**: today only pixel RMSE, p50, p90 and max are emitted, and angular error is optional |
| Correct coarse target | `correct_target` over scored trials | Existing |
| Abstention | `fallback_no_route` over scored trials; the safe outcome, never merged into wrong target | Existing |
| Wrong-target error | `wrong_target` over scored trials | Existing |
| Invalid tracking | `invalid_tracking` over trials | Existing |
| Accidental activation per hour | Count of activations nobody asked for, divided by **scored exposure time**: time the feature was armed with no intended activation, as logged by the harness. A rate is reported only above a minimum exposure frozen before the study; below it the count and the exposure are reported and no rate | **New**: today the head-pointer task reports a total because it records no exposure |
| CPU and memory | Process CPU utilisation and RSS delta, per host | Existing (`Runtime/performance`) |
| End-to-end latency | Frame-to-derived-signal latency and derived-signal age at action, p50 and p95, per host | Existing where measurable; never averaged across unlike machines |
| Failure recovery | Reacquisition time after deliberately induced tracking loss; behaviour when the camera is busy or permission is denied | Existing (reacquisition) plus the R-08 checks |
| Drift | Mean error per time block | Existing |

Every rate is reported with its numerator and denominator. No single "gaze accuracy %" is reported.

## 7. Splits, pairing and leakage

- **Unit of analysis is the participant**, then device, then session. Frames and trials from one
  participant, device or session never appear on both sides of any split.
- **Adjacent frames and trials are not independent.** They are never shuffled across a train/test or
  tune/evaluate boundary.
- **Calibration points and validation points are disjoint.** Error is measured on points the
  calibration did not use.
- **Any threshold, confidence cut-off or model choice** is made on a development partition split by
  participant or session and then frozen before the evaluation partition is touched. If nothing is
  tuned, say so.
- **Report per participant, device and session**, not only pooled, and report the number of units.
- **Paired comparison.** Candidates are compared on the same participants, screen and calibration
  conditions. Because raw frames cannot be stored, candidates cannot be replayed on recorded video;
  the proposed design is **counterbalanced sequential sessions** (order randomised per participant)
  so that CPU contention and fatigue do not favour one candidate. Running several candidates on the
  same live frame stream is allowed only for accuracy comparisons, never for latency or CPU, because
  the candidates would compete for the same cores.
- **Small samples.** State the number of participants, devices and sessions beside every result.
  A comparison with too few units to support a statement is reported as inconclusive, not ranked.

## 8. CI without hardware

The metric code gets E2-style tests with fake numeric samples and known answers: angular-error
geometry on constructed points, the leakage guard (a split that puts one session on both sides
fails), and report-schema checks. These tests use no camera, no image and no model download.

**Implemented** in `scripts/hci_gaze_compare.py`, tested in `tests/test_hci_gaze_compare.py`:
angular error (and its refusal without the display geometry), nearest-rank median and p95 with `n`,
a participant/session leakage guard, a calibration/validation disjointness check, and a report-shape
check that requires limitations and non-claims, refuses a moving ref as a revision, and rejects any raw
or identifying field (frames, images, landmarks, video, audio, embeddings). Exposure-based rate
suppression is **not** reimplemented: `yazses.eyeeval.analysis` already refuses an hourly rate below a
provisional minimum exposure, and a comparison uses that.

## 9. Live study requirements

A live run needs real hardware, informed participation, and a local-only recording policy that
stores derived metrics and never frames. Participant data is Class C and needs an ethics
determination first (`EVALUATION.md`, E7). Volunteers can withdraw at any time and their data is
removed. Community runs without that process are Class B and stay engineering validation.

## 10. Report template

Every report must contain, in this order: the question; candidates with revisions and licences;
the sessions table (units, devices, conditions); the metrics above with denominators; **negative
and null results**; known limitations; the exact protocol version; and the non-claims in
section 3. A report with no limitations section is incomplete.

## 11. Gate and non-goals

- No recommendation to change runtime behaviour before the #419 co-design work and an ADR-030
  prioritisation decision.
- Not in scope: a new capture source, training or fine-tuning any model, persisting any frame,
  emotion, identity or attention inference, medical or accessibility-effectiveness claims, and any
  Hub upload of data.

## 12. Open questions for the maintainer

1. The minimum exposure time for reporting an accidental-activation rate. The repository already has a
   provisional default (`DEFAULT_MIN_EXPOSURE_S`, 600 s, in `yazses.eyeeval.analysis`); the question is
   whether this study keeps it, and it must be frozen before any study.
2. Whether the first comparison should be restricted to the two shipped backends until a Hub
   checkpoint clears the #694 review.
3. Where the live harness lives. The metric code is a research script outside `src/`
   (`scripts/hci_gaze_compare.py`), so nothing in the daemon imports it; whether a live harness extends
   `yazses gaze measure` or stays a separate script is still open.

Cross-references: epic #692; #694 (provenance, draft PR #704); #701 and #698 (publication gate and
playbook); #104, #414, #418, #419 (eye programme); `design/eye-control/ROADMAP.md`; ADR-030.
