# ADR-012: Opt-In, Local, Encrypted Self-Improvement Loop

**Status:** Accepted
**Date:** 2026-05-29
**Deciders:** Mohsen Seyedkazemi Ardebili

---

## Context

YazSes' transcription pipeline is one-shot: audio → Whisper → clean → filter →
inject, after which every artifact is discarded. Diagnostic logs are metadata-only
by design (ADR-011), so there is no mechanism to learn *why* a transcription was
wrong or to systematically improve accuracy over time. This blocks the product's
first strategic rung — making voice-to-text rock-solid — and the later rungs
(voice-to-action, voice-to-web) that depend on a reliable base.

The obvious lever is to learn from real usage. But ADR-011 makes "zero telemetry,
never persist transcript text, audio stays in RAM" a non-negotiable, CI-enforced
default. A naïve "send usage data home" approach is disqualified outright.

## Decision

Introduce a **self-improvement loop** that is opt-in, entirely local, and
encrypted at rest — tuning *prompts, few-shots, thresholds, and filters*, not
model weights.

1. **Off by default.** Capture is dormant unless `[learning] enabled = true`.
   With it off, the code path is inert and no data is written. This preserves the
   ADR-011 default-off guarantee.
2. **Local only.** The corpus lives at `~/.local/share/yazses/` (`corpus.db` +
   `clips/`). Nothing is transmitted; re-transcription during `yazses tune` runs
   on-device with a local model. No new network egress.
3. **Encrypted at rest.** Text columns and audio clips are AES-256-GCM encrypted
   with a machine-bound key (`corpus.key`, `0600`, generated on first use — the
   SSH-key model). This is lighter than ADR-007's passphrase+PBKDF2 scheme,
   chosen deliberately: the corpus is a frictionless daily-driver capture, not a
   secrets vault. The trade-off is documented in Consequences.
4. **Capture off the hot path.** A background `CorpusWriter` thread does all
   encryption and disk I/O; the dictation pipeline only enqueues and never blocks
   or fails on capture.
5. **Human-in-the-loop tuning.** `yazses tune` *proposes* concrete config diffs
   (Whisper `initial_prompt` vocabulary, `vad_threshold`, STT model, disfluency
   rules, SLM few-shots) backed by counted evidence. Nothing is applied without
   explicit per-proposal approval (`--apply`). No silent config drift.
6. **Multiple error signals.** (a) `yazses mark-wrong` explicit flags; (b) offline
   re-transcription with a larger model as pseudo-ground-truth; (c) a passive
   post-edit/self-correction heuristic computed at analysis time (never live
   keystroke capture).
7. **User-controlled lifecycle.** `yazses corpus status | forget | destroy`, plus
   `retention_days` / `max_corpus_mb` auto-pruning and `redact_patterns` for
   scrubbing sensitive text before storage.

## Consequences

**Positive:**
- Closes the missing feedback loop while staying fully within ADR-011's spirit —
  the data never leaves the machine and capture is opt-in.
- Tuning targets the cheap, safe, interpretable surfaces (prompts/few-shots/
  filters), avoiding the cost and opacity of weight fine-tuning.
- Re-transcription surfaces errors the user never noticed, not just ones they flag.
- Establishes the data foundation later rungs (agentic actions, LoRA per ADR-009)
  can build on.

**Negative / trade-offs:**
- A machine-bound key protects against casual access and accidental cloud sync,
  **not** against a determined local attacker who already has the user's read
  access. Users wanting vault-grade protection should keep capture off or use
  full-disk encryption. (A future option could reuse ADR-007's passphrase scheme.)
- Audio capture grows disk usage; mitigated by `retention_days` + `max_corpus_mb`
  pruning and the `capture_audio = false` option.
- Implemented first in the Python stack (the current daily driver). The Rust v1.0
  core will need an equivalent port — tracked as backlog.
