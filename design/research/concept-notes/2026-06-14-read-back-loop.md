# Read-Back Loop — origin note

> **Written:** 2026-06-14 · **Owner:** Mohsen Seyedkazemi Ardebili
> **Shipped as:** [`design/specs/read-back-loop.md`](../../specs/read-back-loop.md) ·
> [ADR-v2-042 — Personal Read-Back Voice](../../adr/adr-v2-042-personal-readback-voice.md) (voice-cloned extension)
> **Tier:** `design/` — public. Historical origin note; the spec and ADR above are the
> current source of truth.

## The idea

The pitch imagined a blind writer with no monitor on and no screen reader running: hold
the key, speak a sentence, let go, and hear it read back in a calm voice — "yes" commits
it, "no" discards it, "correct *Sienna*" fixes the one name that keeps getting mangled.
The point was that the screen stops being merely optional and becomes genuinely absent —
dictation as a closed loop of ears and mouth, not "talk, then go check the screen."

## What shipped

The loop shipped as `src/yazses/tts/` plus daemon wiring, offering offline read-back with
spoken accept/reject/correct, wired to the `read-back` feature toggle (**off by default**,
accessibility category). A later extension, ADR-v2-042, personalizes the read-back voice
by cloning the user's own enrolled voice instead of a generic synthetic one — layered on
top of the original loop rather than replacing it, reusing the `voiceprint/` enrollment
infrastructure shared with Cocktail Filter and Voiceprint Mind.
