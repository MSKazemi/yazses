# Eye / camera control test and validation plan

This plan makes hardware-heavy accessibility work reviewable without requiring every contributor or
CI runner to own the same camera, face, desktop, or eye tracker.

## Test pyramid

### Layer A — pure unit tests (required for every PR)

Inputs are numeric values and fake clocks; no camera, display server, or optional dependency.

Cover:

- calibration transforms;
- gaze confidence;
- route decisions;
- implicit calibrator update/reject/apply;
- head-pose → cursor mapping;
- dwell state machine;
- face-gesture hysteresis/debounce;
- gesture-chord resolution;
- consequence/confirmation policy.

A task that can be expressed as pure state but only has a webcam test is not done.

### Layer B — adapter contract tests (required)

Inject fake `cv2`, MediaPipe, platform APIs or portal D-Bus responses, following the pattern already
used by `tests/test_gaze_mediapipe.py` and `tests/test_gaze_l2cs.py`.

Required invariants:

- optional modules are imported lazily;
- disabled camera features do not probe/open a camera;
- one camera owner serves multiple consumers;
- camera close is idempotent;
- MediaPipe failure degrades without crashing dictation;
- no frame bytes are written;
- signal timestamps/confidence propagate correctly;
- a consumer never needs to import MediaPipe types.

### Layer C — deterministic numeric trace replay (new)

Store small JSON fixtures containing **derived numbers only**, for example:

```json
{
  "name": "brow-raise-single-event",
  "fps": 30,
  "samples": [
    {"t": 0.000, "brow_inner_up": 0.12, "confidence": 0.98},
    {"t": 0.033, "brow_inner_up": 0.14, "confidence": 0.98}
  ],
  "expected_events": []
}
```

Fixtures must not contain photos, face meshes, biometric templates, screenshots, gaze-labelled text,
or identity metadata.

Use traces for:

- expression detector enter/exit thresholds;
- one-event-per-gesture;
- refractory period;
- head jitter / deadzone;
- dwell reset on movement;
- signal loss;
- pointer freeze during a face commit gesture;
- false-activation regression.

### Layer D — platform contract tests

Pointer injection backends get a common suite:

- move relative;
- click press + release ordering;
- scroll;
- unsupported operation reports capability honestly;
- close/restart;
- failure does not repeat the previous action.

For XDG RemoteDesktop, fake the D-Bus exchange and assert:

- POINTER is requested only when a pointer consumer is enabled;
- existing KEYBOARD request remains intact when dictation injection needs it;
- restore token behavior is unchanged;
- pointer methods are never sent before permission/session start;
- refusal is surfaced and no action occurs.

### Layer E — live hardware smoke test (required before changing feature tier)

Unit tests can prove control logic, not real vision accuracy. Hardware validation is separate and
must report environment.

Minimum report:

| Field | Examples |
|---|---|
| OS/session | Ubuntu 26.04 GNOME Wayland; Windows 11; macOS |
| camera/tracker | built-in webcam; Logitech; Tobii model |
| lighting | front-lit / side-lit / window behind |
| glasses | yes/no; optional description |
| display | size/resolution/scale |
| viewing distance | approximate cm |
| feature/config | gaze/headpointer/face switch + thresholds |
| session duration | minutes |
| failures | route errors, phantom switches, lost tracking |
| CPU/FPS | observed, not claimed as universal |
| privacy check | no frames written; no unexpected network |

Do not ask contributors to publish their face, video, disability, diagnosis, or typed content.

## Capability-specific validation

### Gaze routing

Already covered in CI:

- map raw gaze through calibration;
- route only above confidence threshold;
- fallback to focused window;
- preserve burst gaze snapshot for deixis;
- destructive confirmation.

Hardware metrics to collect:

- calibration error;
- wrong-window rate;
- no-route/fallback rate;
- drift over time;
- error by lighting/glasses/device when volunteered.

**Do not use a single "accuracy %" without defining the target and denominator.**

### Implicit calibration

Unit gates:

- low-confidence sample rejected;
- high residual/outlier rejected;
- update cost does not grow with sample history;
- candidate cannot replace baseline when held-out error is worse;
- persisted baseline survives crash/failure;
- rollback returns exact prior map.

Hardware comparison:

1. run explicit calibration;
2. record baseline validation error;
3. collect natural clicks;
4. evaluate candidate on a held-out set;
5. report before/after error and elapsed session time.

### Head pointer

Pure gates:

- inside deadzone -> zero delta;
- sign/direction mapping is correct;
- signal loss -> zero motion;
- movement after re-centre uses new neutral;
- dwell resets after moving beyond radius;
- exactly one click per dwell until re-armed;
- pausing suppresses both motion and dwell click.

Hardware observations:

- target acquisition time for large targets;
- overshoot/correction count;
- accidental clicks/hour;
- whether speaking changes head control;
- whether face-gesture commit disturbs pointer position.

No universal throughput threshold should be invented before baseline data exists.

### Face switch

Pure gates:

- neutral calibration establishes baseline without emitting an event;
- crossing enter threshold for less than minimum hold emits nothing;
- sustained deliberate gesture emits exactly one event;
- detector must cross exit threshold before re-arming;
- refractory interval suppresses bounce;
- low confidence emits nothing;
- ordinary blink trace does not trigger a default non-blink gesture.

Primary hardware metric:

> **false activations per hour**, by configured gesture.

Also record missed deliberate activations. Both matter; optimizing only recall can make a switch
unusable.

### Wayland pointer

Live smoke:

- portal consent shown only when needed;
- restored session works after restart when compositor supports restore;
- motion/click reaches a normal Wayland app;
- denial leaves YazSes usable for ordinary dictation;
- no `/dev/uinput` or privileged helper is required for the portal path.

### Hands-free bundle

Scenario test:

1. start from keyboard/mouse untouched;
2. target a text field;
3. dictate text;
4. move pointer to a large control;
5. select/commit;
6. recover from deliberately obscuring the camera;
7. pause the hands-free controls;
8. resume;
9. invoke a destructive action and verify confirmation;
10. quit/disable and verify camera release.

A bundle is not ready if any step requires an undocumented terminal command.

## Performance / resource measurements

Record rather than guess:

- FaceLandmarker FPS;
- camera resolution;
- CPU utilization;
- memory delta;
- frame-to-signal latency;
- signal-to-pointer latency;
- dropped-frame rate;
- number of physical camera opens.

The architectural hard gate is **one physical camera owner**, not a specific FPS chosen without data.

## Privacy and security assertions

Tests/review must confirm:

- feature disabled -> no camera open;
- camera frames remain in memory;
- no network egress is added by runtime perception;
- model download follows the existing explicit/lazy model path;
- logs contain state/error summaries, never raw landmarks or frame dumps by default;
- measurement export contains derived metrics only;
- face switch performs no identity/emotion inference;
- destructive actions still pass through existing confirmation policy.

## CI commands

At minimum, task PRs run the narrow tests named in their issue plus:

```sh
uv run python -m pytest tests/ -q
uv run ruff check .
uv run mypy src/yazses
```

If the full repository currently has an unrelated known failure, the PR must show the narrow suite
green and link the pre-existing failure rather than weakening/skipping a new test.

## Tier promotion rule

A feature may move from planned -> experimental when:

- runtime path exists;
- hermetic CI exists;
- disable/failure paths are honest;
- privacy rules are satisfied;
- setup/troubleshooting docs exist.

Experimental -> recommended additionally requires:

- real-user/hardware evidence across more than one environment;
- false-activation/error measurements appropriate to the modality;
- no unresolved severe accessibility safety issue;
- defaults justified by data rather than one developer's setup.


## Evaluation level cross-reference

This test plan describes *how* to test individual contracts. The programme-wide evidence ladder and
cross-platform/person replication rules live in [EVALUATION.md](EVALUATION.md).

Use [METRICS.md](METRICS.md) for exact field definitions and provenance. Use
[DATA_SHARING.md](DATA_SHARING.md) before asking a community tester to post a result.

Automated implementation work is tracked by #421–#424. Public no-code hardware slots are #428–#437.
Research protocol/analysis work is #425–#427.

A public hardware report should default to `study_mode=community_qa`. It becomes
`study_mode=research` only when collected under a named research protocol; changing the JSON label
after the fact is not consent.
