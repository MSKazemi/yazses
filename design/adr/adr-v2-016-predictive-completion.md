# ADR-v2-016 — Predictive Dictation Completion

**Status:** Accepted (2026-07-02) · Wave D
**Context links:** [[adr-v2-000-interaction-layer]], [[adr-v2-009-personal-adapter]] (n-gram bias), [[adr-013-llm-cleanup]] (llama.cpp), [[adr-011]]

## Context

The Personal Adapter (ADR-v2-009) only mines n-grams into Whisper's `initial_prompt`
(biasing recognition). The Wave D research (#4) proposes generative next-text prediction:
a tiny on-device LLM (Gemma 3 270M INT4 ≈125 MB, or SmolLM3) proposes the rest of a
sentence on a pause, accepted by voice ("accept"/"take it"). No offline dictation tool
offers voice-accepted completions; great for boilerplate and low-effort/accessibility use.

## Decision

Add an opt-in **predictive completion**: `[predict] enabled`, `model_path`,
`max_tokens`, `accept_phrases`. A pure layer parses accept/decline phrases and merges an
accepted suggestion into the buffer; the generator is lazy behind a `[predict]` extra
(reuse the existing `llama-cpp-python` dep from ADR-013) and fed the corpus n-grams for
personalization. Runs in a background thread and only surfaces on a pause — never blocks
injection. OFF by default.

## Consequences

- Reuses the llama.cpp path already present for LLM cleanup; no new base dep.
- Background-thread + pause-gated so the hold-to-talk latency budget is untouched.
- Caveat: suggestions can be wrong → always explicit voice-accept, never auto-commit.
  On-device only (ADR-011); the model sees only local text.

## Wiring (2026-10-22, #164)

Written in a code-only wave; untested on real hardware and with a real model.

- **Where it runs.** After a dictated burst is typed, `Daemon._predict_submit` hands the
  text to `predict/runtime.py`'s single worker thread, which serves only the latest
  request and calls `predict/generator.py::LlamaCompleter` (greedy, `stop=["\n"]`,
  `[predict] max_tokens`). The hold-to-talk path never waits on the model. `llama_cpp`
  is imported on the worker the first time a completion is asked for.
- **No `predict` extra.** The generator reuses `llama-cpp-python`, the package of the
  `slm` extra (as `notes` does). With no `[predict] model_path`, no llama-cpp-python, or
  a path that is not a file, the daemon logs the reason once and stays dormant;
  `yazses features enable predict` prints the same reason. Enabling does not install
  llama-cpp-python (no `_FEATURE_DEPS` entry yet).
- **Display surface.** The existing notification path (`system/notify.py`), not the
  overlay: the overlay draws rings, not text, and putting text on it would need a new
  `status` field. The toast expires with the offer. It is the one notification whose
  body is derived from dictation, so it passes `log_body=False` and the daemon logs only
  the word count above DEBUG.
- **Accept/decline.** The pure `predict/session.py` resolves the next burst with this
  ADR's `parse_accept` (whole utterance only). Accept types the suggestion, through the
  no-text-target check and Field-Aware Dictation, and records it so "scratch that"
  removes it. Decline types nothing. Anything else withdraws the offer and is dictated.
  An accept up to 20 s after the 10 s expiry is consumed and types nothing, so the word
  "accept" is not typed in place of a stale suggestion.
- **Staleness.** Every hold start, typed burst and non-dictation change moves an epoch;
  a generator result for an older epoch is dropped unseen. A burst that changes the
  screen any other way (a command, an undo, a refusal) clears the offer and the context.
- **Firing rate (ADR-021).** An offer needs at least three words of context and two new
  words; one is shown per typed burst at most. The thresholds and the 10 s expiry are
  module constants in `predict/session.py`, not config keys.
- **Not done.** The ADR's corpus n-gram personalisation, a configurable accept phrase
  list (`accept_phrases`), and offering on a pause *during* a hold are not wired.
