# Cocktail Filter — origin note

> **Written:** 2026-06-14 · **Owner:** Mohsen Seyedkazemi Ardebili
> **Shipped as:** [`design/v2-cognitive-layer/02-cocktail-filter.md`](../../v2-cognitive-layer/02-cocktail-filter.md) ·
> **Companion:** [`hci-corpus.bib`](../hci-corpus.bib)
> **Tier:** `design/` — public. This is a historical origin note, not a live proposal: the
> feature it describes has shipped, off by default, and the implementation doc above is
> the current source of truth.

## The idea

The pitch was the human cocktail-party effect applied to a dictation daemon: enrol a
voiceprint once, and treat every other voice in the room — a roommate on a call, a TV, an
open-plan office — as if it were silence. The job story was simple: hold the key in a
noisy kitchen, and only the enrolled voice reaches the transcript.

The state-of-the-art survey behind it split the problem into three layers of very
different maturity. A **personal-VAD gate** — a small (~130K-parameter) speaker-conditioned
classifier that keeps or drops whole frames by speaker — was judged solved for on-device,
CPU-real-time use. **Target-voice suppression** (attenuating an interferer while keeping
the target speaker intelligible, e.g. VoiceFilter-Lite-class models) was judged partial:
demonstrated, but not available as a pip-installable, permissively-licensed CPU artifact.
Full **source separation** (recovering both speakers cleanly) was judged out of scope —
real, but GPU-tier, not a laptop-CPU feature.

## What shipped

The gate layer shipped as `src/yazses/audio/personal_vad.py`, reusing the enrollment and
encrypted-storage infrastructure YazSes already had. It is **off by default**: live
testing after the initial build showed the sub-second window a real-time gate has to work
with makes ECAPA-class speaker embeddings unreliable enough to false-reject the enrolled
user's *own* voice — the opposite of the intended effect. That result, and the reasoning
behind keeping the feature off pending a better short-window embedding, is recorded in
`design/v2-cognitive-layer/02-cocktail-filter.md` and in the codebase itself. The
suppression layer (P2) was never built — no permissively-licensed CPU-real-time model was
found, exactly as the original survey flagged as the open risk.
