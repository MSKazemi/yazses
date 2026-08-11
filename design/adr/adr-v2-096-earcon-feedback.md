# ADR-v2-096 — Earcon Feedback Language (non-speech eyes-free state cues)

**Status:** Accepted (2026-07-02) · Wave L
**Context links:** [[project_readback_loop]] (speech feedback), confidence (visual), overlay (visual), [[adr-011]]

## Context

Wave L research (#6) — Read-Back is *speech* (slow, verbose); Confidence Ink and the Voice-Activity
Overlay are *visual*. A structured **non-speech auditory** feedback grammar — a rising two-note motif
for "recording started", a muted buzz for "low confidence", a distinct chime for "command executed" —
is faster, less intrusive, and works with no screen, a gap in the current set. Anchor: Brewster et
al., *An evaluation of earcons* (ACM TOCHI 1993); Gaver, *Auditory Icons* (1986); Walker et al.,
*Spearcons* (Human Factors 2013) — structured non-speech audio conveys interface state faster than
speech and improves eyes-free navigation.

## Decision

Add an opt-in **Earcon Feedback**: `[earcon] enabled=false`. Pure cores in `earcon/tones.py`:
`ToneSpec(freq_hz, dur_ms, envelope)`, `earcon_for(event, confidence=None)` → a motif (list of
`ToneSpec`; low confidence overrides to a buzz), and `render_earcon(specs, fs)` → a numpy waveform
(sine synth + linear/buzz envelope). Numpy is already a core dependency; no heavy extra. OFF by
default.

## Consequences

- Fast, unintrusive, screen-free state feedback; complements (precedes) Read-Back.
- Fully pure (mapping + numpy synth) → 100% testable, zero new dependency.
- Privacy (ADR-011): synthesized locally; nothing stored or sent.
- Caveat: a fixed motif vocabulary (user-remappable is a later tier); off by default.
