# Wave E — feature research (SoA sweep, 2026)

**Date:** 2026-07-02 · **Tier:** `design/` — public engineering research · **Author:** Mohsen Seyedkazemi Ardebili
**Companion:** fed [adr-v2-025](../../adr/adr-v2-025-hallucination-guard.md) through
[adr-v2-034](../../adr/adr-v2-034-vocal-strain-guard.md). See the [waves index](README.md).

> A snapshot of the field on the date above, kept as the research record behind the ADRs it fed.
> Feature status should be checked against `yazses features` and the linked ADRs, not this note.

10 features distinct from the 24 already designed/shipped before this wave (13 v2 + 11 Wave D). All
respect on-device / off-by-default / lazy-extra invariants. Ranked strongest-first.

## Build tiers
- **Ship-now (pure logic):** #1 Hallucination Guard, #2 Phonetic Corrector, #7 Voice Snippets.
- **High-value modes (grammar core + deferred small model):** #3 Spoken Math→LaTeX, #5 Multi-User Voiceprint Profiles, #6 Spoken Code Mode.
- **New hands-free modalities (medium ML/UX):** #4 Semantic Endpointing, #8 Wake-Word, #10 Voice Mouse Grid.
- **Speculative (needs threshold validation):** #9 Vocal-Strain Guard.

## Features

1. **Hallucination Guard** — drop Whisper's fabricated spans (ghost "Thank you.", "please
   subscribe", loops) on silence/noise before typing. Anchor: Careless Whisper (FAccT 2024,
   arXiv 2402.08021); distribution-shift (arXiv 2502.12414). Pure: threshold gate on
   `no_speech_prob`/`avg_logprob`/`compression_ratio` + loop/n-gram repetition + curated
   silence-phrase blacklist + word-rate sanity. `[filters.hallucination]`. Distinct from
   Confidence Ink (words, not whole fabricated spans). → [adr-v2-025](../../adr/adr-v2-025-hallucination-guard.md).

2. **Phonetic Corrector** — fix mis-heard proper nouns/commands in phoneme space ("Cuber
   Netties"→"Kubernetes"). Anchor: espeak-ng/phonemizer G2P + Double Metaphone; MathSpeech
   post-hoc pattern (arXiv 2412.15655). Pure: phonemize personal vocab → weighted phoneme
   edit-distance match on output. `[filters.phonetic]`. Distinct: corrects *output* vs
   Context-Primed/Adapter biasing the *prior*. → [adr-v2-027](../../adr/adr-v2-027-phonetic-corrector.md).

3. **Spoken Math → LaTeX** — "integral from zero to infinity..."→`\int_0^\infty ...`. Anchor:
   MathSpeech (AAAI 2025, arXiv 2412.15655); Speech-to-LaTeX (ICLR 2026, arXiv 2508.03542).
   Pure: spoken-math grammar (numbers/operators/greek/frac/sqrt). Deferred: T5-small int8
   behind `mathspeech` extra. `[math]` + command key. → [adr-v2-032](../../adr/adr-v2-032-spoken-math-latex.md).

4. **Semantic Endpointing** — tap-once, speak, auto-stop at true sentence end. Anchor: Smart
   Turn v2 (Pipecat, HF open weights, wav2vec2, ~60MB/~400ms/14 langs). Pure: endpoint state
   machine (silence-timeout + max-duration). Deferred: Smart Turn v2 ONNX behind `turn` extra.
   `[endpoint] semantic` / `[hotkey] mode=tap`. New activation axis (motor impairment). → [adr-v2-029](../../adr/adr-v2-029-semantic-autostop.md).

5. **Multi-User Voiceprint Profiles** — auto-switch vocab/hotkey/cleanup per enrolled speaker.
   Anchor: reuse ECAPA d-vector infra (arXiv 2005.07143). Pure: multi-embedding store +
   nearest-profile + per-profile config overlay. `[voiceprint] multi_profile`. Distinct from
   Voice Guard (binary gate vs N-way routing). Embeddings stay in the encrypted corpus (see
   [adr-012](../../adr/adr-012-self-improvement-loop.md)). → [adr-v2-028](../../adr/adr-v2-028-multiuser-voiceprint-profiles.md).

6. **Spoken Code Mode** — syntax-aware programming by voice (spoken symbols + casing). Anchor:
   Talon/Serenade/Cursorless paradigm. Pure: code-formatting grammar (symbols→punct, casing,
   keywords). Deferred: LSP identifier completion via the existing Neovim bridge. `[code]` + key.
   → [adr-v2-031](../../adr/adr-v2-031-spoken-code-mode.md).

7. **Voice Snippets** — spoken text-expander ("insert my signature"→stored template). Anchor:
   TextExpander/espanso, voice-triggered. Pure: `snippets.toml` (trigger→template) + command-
   path match + inject. `[snippets]`. Distinct: `[macros]` are keystrokes, not text templates.
   → [adr-v2-026](../../adr/adr-v2-026-voice-snippets.md).

8. **Wake-Word Activation** — hands-free start on a custom keyword. Anchor: openWakeWord
   (dscripka), microWakeWord (OHF-Voice, TFLite-micro). Pure: activation state machine + rolling
   buffer + false-accept guard. Deferred: openWakeWord ONNX behind `wakeword` extra. `[wakeword]`.
   The only always-listening feature in the set → the strongest opt-in gating. → [adr-v2-033](../../adr/adr-v2-033-wake-word.md).

9. **Vocal-Strain Guard** — voice-RSI break reminders from jitter/shimmer/HNR trend. Anchor:
   clinical dysphonia biomarkers; `parselmouth` already shipped (Prosody Ink). Pure: per-utterance
   biomarkers + session trend + threshold alert. `[voicehealth]`. Advisory-only, not diagnostic;
   thresholds need calibration. Distinct: longitudinal well-being, not transcription. → [adr-v2-034](../../adr/adr-v2-034-vocal-strain-guard.md).

10. **Voice Mouse Grid** — continuous pointer control by voice (Talon grid, "three…seven…click").
    Anchor: Talon numbered/mouse-grid. Pure: recursive grid-subdivision math + spoken-number
    grammar; reuses the overlay + injector. `[mousegrid]`. Universal pixel fallback where
    AT-SPI Pilot (needs a tree) and Gaze (targets windows) fail. → [adr-v2-030](../../adr/adr-v2-030-voice-mouse-grid.md).

## Cross-cutting synergy
#4 semantic endpoint + #8 wake-word + #10 voice mouse compose into a complete zero-touch
operating mode — a coherent accessibility bundle worth designing together.

## Honest caveats, from the original sweep
- #3/#4/#8 need real on-device models (all open weights, none cloud); pure cores ship first.
- #9 thresholds need empirical calibration → advisory-only.
- #8 is the only always-listening feature → hardest opt-in + hard local-only guarantee.

Citations here have not been re-verified against [`research/verify_refs.py`](../verify_refs.py).
