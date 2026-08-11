# ADR-v2-043 — Gesture Chords

**Status:** Accepted (2026-07-02) · Wave F
**Context links:** [[adr-v2-023-semg-silent-input]] (sensor sibling), [[adr-v2-030-mouse-grid]], [[adr-011]]

## Context

The Wave F research (#9) proposes binding multi-input "chords" — a held hotkey combined with a
head nod, a second key, or an sEMG squeeze — to actions (send, undo, switch profile) so power
users get modal control without leaving hold-to-talk. Anchors: MediaPipe head-pose, the
existing EMG YESP backend, chorded-input HCI literature. Nothing in the prior 42 composes
simultaneous inputs into a single action.

## Decision

Add an opt-in **Gesture Chords**: `[gesture] enabled=false`. The pure core is an input-agnostic
chord resolver: `normalize_chord(keys)` canonicalizes a set of simultaneously-held inputs into
a stable chord id, and `resolve_chord(keys, mapping)` maps it to a bound action (or None). The
physical sensors (head-pose via MediaPipe, sEMG via the existing EMG backend) are lazy behind
their own extras and only feed input tokens into the resolver. OFF by default.

## Consequences

- Input-agnostic: the same resolver serves key-combos today and head/sEMG chords when those
  backends are present.
- Pure normalization/lookup → fully testable with no hardware.
- Privacy (ADR-011): resolver sees only abstract input tokens; sensor data stays with its backend.
- Caveat: chord collisions/false triggers → conservative empty default mapping, off by default.
