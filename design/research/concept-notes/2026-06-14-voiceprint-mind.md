# Voiceprint Mind — origin note

> **Written:** 2026-06-14 · **Owner:** Mohsen Seyedkazemi Ardebili
> **Shipped as:** [`design/v2-cognitive-layer/01-voiceprint-mind.md`](../../v2-cognitive-layer/01-voiceprint-mind.md) ·
> [ADR-v2-009](../../adr/adr-v2-009-personal-adapter.md)
> **Tier:** `design/` — public. Historical origin note; the implementation docs above are
> the current source of truth.

## The idea

The pitch: every dictation tool meets a new user cold, mishearing names, jargon, and
accents it has never encountered. The dream was a recogniser that quietly gets more
fluent in *you* the more you talk — with no training UI, no labelling chore, and the
resulting personalization living only on the user's own disk, never a vendor's profile.

## What shipped

The first, cheap layer of this — biasing Whisper's decoding with the user's own
frequent vocabulary and personal terms mined from their own dictation history, no model
training involved — shipped as `src/yazses/personalize/prompt_builder.py`, wired to the
`personalize` feature toggle (**off by default**). The heavier half of the original
idea — an opt-in nightly LoRA fine-tune of the acoustic model itself, gated on a
held-out WER improvement before ever taking effect — is designed and specified but not
yet built; it remains a documented next step rather than a shipped capability.
