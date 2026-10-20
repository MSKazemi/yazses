# Wave D — feature research (SoA sweep, 2026)

**Date:** 2026-07-02 · **Tier:** `design/` — public engineering research · **Author:** Mohsen Seyedkazemi Ardebili
**Companion:** fed [adr-v2-014](../../adr/adr-v2-014-speech-translation.md) through
[adr-v2-024](../../adr/adr-v2-024-vlm-screen-commanding.md). See the [waves index](README.md).

> A snapshot of the field on the date above, kept as the research record behind the ADRs it fed.
> Feature status (shipped, dormant, or design-only) should be checked against `yazses features`
> and the linked ADRs, not against this note.

Distinct from the 13 v2 features designed before this wave; all candidates respect the
project's core invariants (on-device, zero telemetry, off by default, dependency-isolated).
Ranked strongest-first.

## Build tiers
- **Ship-now** (buildability × value): #3 denoise, #2 X→English translate, #4 predictive completion, #6 tone formatting.
- **Medium:** #1 meeting scribe, #5 voice-guard, #8 RAG, #7 codec streaming.
- **Research:** #9 silent-speech, #10 VLM commanding, #11 atypical LoRA.

## Features

1. **Ambient Meeting Scribe** — on-device streaming diarization ("who said what") + summary.
   Anchor: NVIDIA Streaming Sortformer (arXiv 2507.18446); reuse enrolled voiceprint to tag "you".
   Extra `[scribe]`. Medium. Caveat: CPU real-time on ≥3 speakers needs a lighter clustering fallback.
   → [adr-v2-019](../../adr/adr-v2-019-meeting-scribe.md).

2. **Real-time offline speech translation** — dictate in L1, inject L2. Anchor: Whisper `task=translate`
   (X→English, zero new deps) → Meta SeamlessM4T v2 (arXiv 2312.05187) for N-to-M. Extra `[translate]`.
   Easy (X→En) / Hard (Seamless). Caveat: Seamless heavy on CPU — ship X→English first.
   → [adr-v2-014](../../adr/adr-v2-014-speech-translation.md).

3. **Real-time noise-suppression front-end** — denoise/dereverb before STT. Anchor: DeepFilterNet3
   (112K–3.58M params, live plugin). Extra `[denoise]`. Easy. Attacks the "Silent audio — discarding"
   failure mode. Caveat: over-suppression clips soft consonants → graded on/off + re-run mic-level.
   → [adr-v2-015](../../adr/adr-v2-015-noise-suppression.md).

4. **Predictive dictation completion** — tiny on-device LLM proposes sentence end; accept by voice.
   Anchor: Gemma 3 270M (INT4 ~125MB) / SmolLM3, fed corpus n-grams. Extra `[predict]`. Easy/Medium.
   Caveat: tight latency in hold loop → background thread, surface on pause, never block injection.
   → [adr-v2-016](../../adr/adr-v2-016-predictive-completion.md).

5. **Continuous voice-biometric gate + anti-deepfake** — inject only when live speaker matches the
   enrolled voiceprint; reject synthetic/replay. Anchor: ASVspoof 5 (arXiv 2601.03944), AASIST/SSL
   (arXiv 2502.03559). Extra `[voiceguard]`. Medium. Caveat: false-reject risk → off by default + override.
   → [adr-v2-018](../../adr/adr-v2-018-voice-biometric-guard.md).

6. **Emotion / tone-aware formatting** — affect→formatting (auto `!`, emphasis) beyond pause→sentence.
   Anchor: emotion2vec / ParaS2S (arXiv 2511.08723). Extra `[affect]`. Easy/Medium. Caveat: SER is
   speaker/culture-variable → conservative default (emphasis + `!` only).
   → [adr-v2-017](../../adr/adr-v2-017-tone-aware-formatting.md).

7. **Neural-codec ultra-low-latency streaming** — streaming-native STT ~80ms. Anchor: Kyutai STT +
   Mimi codec (Jun 2025), MLX on-device. Extra `[streaming-codec]`. Medium. Caveat: English/French-centric
   → keep faster-whisper default multilingual.
   → [adr-v2-022](../../adr/adr-v2-022-codec-streaming.md).

8. **Voice-grounded RAG over personal notes/docs** — ask by voice, retrieve+cite from local docs.
   Anchor: EmbeddingGemma (308M, Sep 2025) + sqlite-vec + Gemma 3 270M. Extra `[rag]`. Medium.
   Caveat: hallucination → require inline citations, extractive fallback.
   → [adr-v2-020](../../adr/adr-v2-020-voice-grounded-rag.md).

9. **Silent-speech / subvocal (sEMG)** — dictate by mouthing silently. Anchor: microneedle SSI
   8.5% WER (S2666053925001249), emg2speech (arXiv 2510.23969); extends the existing `EMGBackend`. Extra
   `[silentspeech]`. Hard. Caveat: hardware + accuracy bottleneck → experimental, opt-in only.
   → [adr-v2-023](../../adr/adr-v2-023-silent-speech-semg.md).

10. **Pure-vision screen commanding (VLM)** — "click the blue Export button" where AT-SPI is empty.
    Anchor: Microsoft OmniParser V2, ShowUI, Florence-2. Extra `[screenvision]`. Hard. Frames stay
    in-RAM only (see [adr-011](../../adr/adr-011.md)). Caveat: on-device VLM latency → scope to
    icon+text grounding, AT-SPI primary.
    → [adr-v2-024](../../adr/adr-v2-024-vlm-screen-commanding.md).

11. **Atypical-speech personalization via corpus LoRA** — adapt the acoustic model to dysarthric/accented
    speech. Anchor: Universal Personalizer (arXiv 2509.15516), dysarthric LoRA 13.9% WER Euphonia
    (arXiv 2505.12991); extends Dysfluency Mode + held-out gate. Extra `[atypical]`. Hard. Caveat:
    on-device fine-tune is compute-heavy → idle/plugged-in only, validate on held-out data.
    → [adr-v2-021](../../adr/adr-v2-021-atypical-speech-adapter.md).

## Boundaries vs existing features
- #8 RAG ≠ Spoken Recall (generative+cited over arbitrary docs, not search over past dictations).
- #2 Translate ≠ Code-Switch (cross-lingual output vs keep-native spans).
- #10 VLM ≠ AT-SPI Pilot (vision fallback when the tree is empty).
- Personal voice-clone read-back (Sesame CSM-1B) was an honorable mention (incremental over the
  existing Kokoro read-back).

Citations here have not been re-verified against [`research/verify_refs.py`](../verify_refs.py).
