# ADR-v2-137 — Face gestures emit switch intent; they never execute desktop actions directly

**Status:** Proposed (2026-09-22)  
**Context links:** [[adr-v2-043-gesture-chords]], [[adr-v2-052-head-pointer]], [[adr-v2-129-killer-features-10x]], [[adr-v2-135-shared-camera-perception]]

## Context

MediaPipe Face Landmarker can expose blendshape coefficients that make deliberate facial expressions
possible as accessibility switches. A naive implementation could map "mouth open" directly to
`mouse.click()` or "raise brow" directly to "send".

That is the wrong boundary.

Facial movement is noisy and context-dependent:
- ordinary speech changes the mouth;
- blinking is involuntary and frequent;
- a deliberate expression can move the head, disturbing a head-driven pointer;
- thresholds vary across people, cameras and lighting;
- a misfire can be much more costly than a wrong typed character.

YazSes already has two useful abstractions:
- activation-source / modality seams for input triggers;
- Gesture Chords as an input-agnostic token resolver.

## Decision

A face detector may emit only a **normalized, abstract switch event**.

Conceptually:

```text
blendshape trace
  -> calibrated detector
  -> FaceSwitchEvent(kind, phase, confidence, timestamp)
  -> mapping / Gesture Chord / activation policy
  -> confirmation policy when required
  -> action
```

The detector never imports or calls:
- PointerSink;
- daemon command dispatch;
- text injector;
- window control.

## Event rules

An event must carry enough information to avoid edge ambiguity:

- gesture kind;
- timestamp;
- confidence/quality;
- activation phase where relevant (pressed/released or fired);
- optional source metadata needed for debugging that is not biometric identity.

No raw frame or face mesh belongs in the event.

## Detector requirements

A shipping detector must support:

1. neutral/personal baseline;
2. separate enter/exit thresholds;
3. minimum hold duration;
4. refractory/debounce period;
5. confidence gate;
6. freshness timeout;
7. exactly one event per intended discrete gesture unless configured as a hold switch.

## Default gesture policy

- **Blink is never the default click/commit.**
- Mouth-open cannot be recommended until ordinary speech false activations are measured.
- Default mapping is empty/off until field evidence supports a preset.
- Unknown gesture labels do nothing.

## Action policy

The mapping layer may bind a switch to:
- hold-to-talk;
- select/click;
- confirm;
- cancel;
- pause/resume pointer;
- a Gesture Chord token.

A face event does not bypass existing confirmation for destructive desktop operations.

## Interaction with Head-Pointer

When a configured commit expression is active, the control layer may freeze Head-Pointer motion for
the gesture interval so facial effort does not also move the target.

This freeze is a composition policy, not part of the detector.

## Alternatives considered

### Direct gesture -> action callbacks

Rejected. It couples perception to consequences and makes safety/testing/default changes difficult.

### Treat face gestures as Gesture Chords only

Rejected as the only interface. A simple switch should not require chord configuration, though it can
feed the same resolver.

### Generic emotion/expression classifier

Rejected. YazSes needs deliberate control events, not emotion inference. The programme does not infer
identity, mood, attention or medical state from the face.

## Consequences

Positive:
- pure detector is easy to test with numeric traces;
- same switch can drive different actions;
- safety/confirmation remains centralized;
- future non-face switches can share action mappings.

Costs:
- requires an explicit adapter/mapping layer;
- thresholds need per-user calibration and field evidence;
- UI/config must explain mappings clearly.

## Implementation

See:
- `design/specs/eye-face-switch.md`;
- #406–#409;
- `design/eye-control/RISK_REGISTER.md`.
