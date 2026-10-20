# Dysfluency-Friendly Mode — origin note

> **Written:** 2026-06-19 · **Owner:** Mohsen Seyedkazemi Ardebili
> **Shipped as:** [ADR-015 — Dysfluency-Friendly Mode](../../adr/adr-015-dysfluency-friendly-mode.md)
> **Tier:** `design/` — public. Historical origin note; the ADR above is the current
> source of truth.

## The idea

The pitch: a dictation tool that silently punishes a person for *how* they speak — cutting
off a stutterer's block mid-word because the endpointer mistook the silent struggle for
"done," or transcribing the literal repetitions instead of the sentence the speaker meant
— is solving the wrong problem. The claim, stated as a real bet rather than a hope, was
that most of the fix is available today with no acoustic model retraining at all: a more
forgiving endpointer so blocks and pauses don't truncate the utterance, plus a
post-processing pass that collapses repetitions, prolongations, and blocks into the
intended words, guarded so it never strips a speaker's *intentional* repetition.

## What shipped

The collapse pass shipped as `stt/filters/disfluency.py`'s three-pass filter (filler
removal → 2-gram dedup → self-correction rollback), wired under the `dysfluency` feature
toggle and folded into YazSes's accessibility preset (`RECOMMENDED` tier, not
experimental). It runs offline, on a consumer CPU, with no model training — exactly the
constraint the original card set for itself.
