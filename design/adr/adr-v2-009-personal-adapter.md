# ADR-v2-009 — Personal Speech Adapter (on-device personalization)

**Status:** Accepted (2026-07-02) · Wave B
**Context links:** [[adr-v2-000-interaction-layer]], [[adr-012-self-improvement-loop]] (corpus), [[adr-014-tune-holdout-validation]] (held-out gate), existing `[personalize]` stub

## Context

The accessibility + voice-HCI research (the accessibility research note (internal),
`01-voice-hci.md`) shows few-shot / LoRA personalization from a user's own data beats
speaker-independent baselines (Universal Personalizer: 13.9% vs 17.5% WER on Euphonia;
AdaLoRA+x-vectors ~23% WER cut on SAP), and Apple proved LoRA hot-swap on-device — yet
**no privacy-first desktop tool ships it**. YazSes already has the raw material: an
encrypted correction corpus, `yazses tune` with a held-out validation gate (ADR-014), and
a `[personalize]` stub with `prompt_builder.mine_terms()`.

## Decision

A two-rung, opt-in personalization path, entirely on-device (no audio leaves the machine):
1. **P1 — Prompt mining (nearly free, ship first):** mine frequent personal n-grams +
   vocabulary from the corpus into Whisper's `initial_prompt` (extends existing
   `personalize/prompt_builder.py`). Cheap, safe, immediate.
2. **P2 — Nightly LoRA (gated):** train a small LoRA on the corpus (atypical/accented
   speech), **promoted only if it beats the base model on a held-out corpus slice**
   (reuse ADR-014). Always keep the base as fallback; strictly opt-in, off by default.

Config (existing): `[personalize] enabled=false`, `bias_from_corpus`, `max_prompt_terms`,
`lora`, `lora_base_model`, `lora_min_events`.

## Consequences

- **+** Dictation that adapts to *your* voice/jargon, private and offline — strongest
  accessibility differentiation; P1 is cheap and low-risk.
- **+** Self-validating via the existing held-out gate.
- **−** CPU LoRA is slow + can overfit a small/noisy corpus → the WER gate is a hard promotion
  criterion; P2 stays experimental behind `--force`; base model always retained.
- **−** Requires enough corpus events (`lora_min_events`) → P1 works from day one; P2 waits.
