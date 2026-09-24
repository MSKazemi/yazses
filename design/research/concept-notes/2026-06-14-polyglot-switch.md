# Polyglot Switch — origin note

> **Written:** 2026-06-14 · **Owner:** Mohsen Seyedkazemi Ardebili
> **Shipped as:** [`design/v2-cognitive-layer/04-polyglot-switch.md`](../../v2-cognitive-layer/04-polyglot-switch.md) ·
> [ADR-v2-008](../../adr/adr-v2-008-code-switch.md)
> **Tier:** `design/` — public. Historical origin note; the implementation docs above are
> the current source of truth.

## The idea

The pitch came from lived bilingual experience: real speech doesn't respect language
boundaries mid-sentence, but every dictation tool forces a pick-one-language-per-utterance
mode. The honest boundary was stated up front — this was never a pitch for universal
any-language code-switching (the field can't do that offline yet), but for a single
**user-configured pair**, detecting the seam mid-utterance and transcribing each span in
its own orthography.

## What shipped

Code-switch routing shipped as `src/yazses/polyglot/` — a pure language-identification and
routing layer that parses a configured pair (e.g. `"fa-en"`), picks a span's dominant
language, and detects within-pair switching. It is **off by default**. The
survey's own boundary held: the routing layer is real and shipped, but the
code-switch-adapted transcription model it routes to is trained out-of-band and stays
dormant until an adapter path is configured — the feature is a real, working seam waiting
on a model, not a finished end-to-end capability for an arbitrary pair.
