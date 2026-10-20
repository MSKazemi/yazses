# State of the Art: Local/Offline STT & Dictation Post-Processing (2026-08-07)

**Date:** 2026-08-07 · **Tier:** `design/` — public engineering research
**Companion:** [gaze / EMG / BCI / multimodal input SoA](2026-08-07-hci-input-sota.md) ·
[voice-dictation market landscape](2026-08-07-competitor-landscape.md) ·
[ADR-002: Dual-Stack STT Routing](../../adr/adr-002.md) ·
[ADR-v2-129: Killer Features 10x](../../adr/adr-v2-129-killer-features-10x.md)

All claims cited; numbers marked "~" are approximate or vendor/community-reported
rather than independently verified.

---

## 1. STT engine landscape (beyond faster-whisper)

| Engine | Avg WER | CPU speed (int8) | Streaming | Word ts | License | Python path | Size |
|---|---|---|---|---|---|---|---|
| faster-whisper small.en | ~8–9% | ~8x realtime | LocalAgreement (app-side) | Yes | MIT | native | ~460 MB |
| whisper-large-v3-turbo (CT2 int8) | ~7.5% short-form | heavy on CPU | No | Yes | MIT | faster-whisper | ~1.5 GB |
| Distil-Whisper large-v3 | within ~1% of large-v3 | ~6x faster than large-v3 | No | Yes | MIT | faster-whisper | ~750 MB |
| NVIDIA Parakeet TDT 0.6B v2 (En) / v3 (25 EU langs) | 6.32–6.34% — beats large-v3 (7.44%) | ~30x realtime CPU (~4x whisper-small); no silence hallucination | Pseudo only (chunked, degrades) | Yes (TDT native) | CC-BY-4.0 | `onnx-asr` (pure Python, no torch) or sherpa-onnx int8 | ~600 MB fp |
| Moonshine v2 (2026-02) | Small-stream 7.84% (123 MB), Medium-stream 6.65% (245 MB) | edge-CPU design; 50–258 ms latency | Yes — native streaming encoder | Yes | MIT (English); non-En = non-commercial | ONNX; sherpa-onnx quantized | 26–245 MB |
| Kyutai STT (1b-en_fr / 2.6b-en) | competitive | 1B feasible on strong CPU | Yes — token-level, fixed 0.5 s delay, built-in semantic VAD | Yes | CC-BY-4.0 | moshi Python/Rust/MLX | 1B/2.6B |
| Canary-Qwen 2.5B | 5.63% | too heavy for CPU dictation | No | Yes | CC-BY-4.0 | NeMo | 2.5B |
| SenseVoice-Small | strong zh/yue/en/ja/ko, NAR very fast | very fast | No (chunked) | limited | Apache-2.0 | funasr / sherpa-onnx | ~230 MB |
| Vosk (Kaldi) | worse than whisper-small | realtime on RPi | Yes (true) | Yes | Apache-2.0 | vosk-api | 40 MB–1 GB |

**Headline of 2025–2026:** Parakeet TDT 0.6B changed the local-dictation calculus —
better-than-large-v3 accuracy at less-than-small.en CPU cost, no hallucination on
silence, a permissive license, and pure-Python inference via `onnx-asr`. Several
2025–26 open-source dictation apps added it (Handy, OpenWhispr, MacParakeet,
parakeet-mlx). Caveat: sherpa-onnx maintainers state TDT is *not* designed for true
streaming (issue #2918) — but a hold-to-talk, batch-per-burst pipeline needs fast
batch, which is exactly Parakeet's sweet spot.

Key sources: HF `nvidia/parakeet-tdt-0.6b-v3` · snailtext.app/blog/whisper-vs-parakeet-tdt ·
northflank.com 2026 STT benchmarks · arxiv.org/abs/2602.12241 (Moonshine v2) ·
github.com/moonshine-ai/moonshine · kyutai.org/stt · github.com/kyutai-labs/delayed-streams-modeling ·
k2-fsa.github.io/sherpa/onnx · github.com/istupakov/onnx-asr ·
marktechpost.com 2026-07-23 ASR roundup · github.com/SYSTRAN/faster-whisper/issues/1030.

## 2. Streaming / low-latency dictation

Commercial reference points: Aqua Voice reports starting to listen in <50 ms and
inserting text in 450 ms–1 s (live as-you-speak display); Wispr Flow is cloud-only,
1–3 s to final formatted text. "Instant-feeling" in this space generally means live
partial text during speech plus final text within roughly 500 ms of key release.

Local approaches, ranked by cost:

1. **Fast batch on release (Parakeet TDT)** — at ~30x realtime CPU, a 5 s burst
   decodes in ~170 ms. A hold-to-talk model reaches that bar with no streaming
   machinery — the cheapest win.
2. **Moonshine v2 native streaming** — a sliding-window-attention encoder with
   cached decoder state gives incremental cost per chunk: 148 ms (Small) / 258 ms
   (Medium) measured latency, and its streaming variants *beat* their batch siblings
   on WER. A modern replacement for LocalAgreement-style re-decoding of the whole
   buffer each tick.
3. **Kyutai delayed-streams** — elegant (fixed 500 ms delay, built-in semantic VAD
   that could replace an RMS gate), but 1B params and Rust-recommended serving. Worth
   watching, not yet adopting.
4. **Parakeet chunked pseudo-streaming** — degrades at chunk boundaries; not
   recommended.

## 3. Hotword / contextual biasing

- Whisper's `initial_prompt` mechanism is the weakest form of biasing available: a
  224-token cap, end-weighted attention, a first-30-second-window-only effect, and
  hallucination risk with dense lists (OpenAI prompting guide; arXiv 2502.11572).
- The current state of the art is **decode-time shallow-fusion phrase boosting** on
  CTC/Transducer models. NVIDIA TurboBias (arXiv 2508.07014, in NeMo word boosting)
  rescales token scores against a boosting tree during decode — no retraining, up to
  20K phrases, no measured speed penalty, and it works with Parakeet TDT. CTC-WS is
  the lighter CTC alternative.
- A practical path for a project on this stack: sherpa-onnx exposes transducer
  **hotwords** directly; on the `onnx-asr` path, edit-distance post-correction from a
  vocabulary list is the fallback (arXiv 2410.18363). Either way, moving personal
  vocabulary from `initial_prompt` to real boosting removes both the 224-token cap
  and the hallucination tax.

## 4. Local LLM post-processing for dictation

Laptop-CPU (no GPU), Q4 GGUF via llama.cpp, 2026:

| Model | Size (Q4) | CPU tok/s (laptop-class) | Notes |
|---|---|---|---|
| LFM2.5-350M / 230M (Liquid) | 0.2–0.3 GB | fast (230M: ~42 tok/s on RPi 5) | IFEval 71.7, reported ahead of Qwen3.5-0.8B and Gemma-3-1B; llama.cpp/ONNX/MLX |
| LFM2.5-2.6B | ~2.5 GB | ~113 tok/s on Ryzen AI Max+ 395 | leads its size class on instruction-following in vendor benchmarks |
| Phi-4-mini 3.8B | ~2.3 GB | ~12 tok/s | |
| Gemma 3n / 4 E2B | ~1.5 GB | ~15 tok/s | good multilingual coverage |
| Qwen3-4B-Instruct-2507 | ~2.4 GB | ~8–12 tok/s | Apache-2.0, best quality/size tradeoff observed for rewrite tasks |

- A dictation cleanup pass typically emits ~30–80 tokens. At 12 tok/s that is 3–7 s
  (too slow to enable by default); at LFM2.5 speeds it drops under 1 s. **Speed, not
  quality, is the binding constraint on CPU** for a default-on cleanup step.
- Structured voice edits ("replace X with Y", "make that a bullet list") are common
  in cloud commercial tools. The proven local pattern is: classify edit intent → a
  small LLM emits a constrained JSON/GBNF edit op → apply it deterministically.

## 5. On-device personalization

- Whisper LoRA fine-tuning: large-v3 needs >30 GB VRAM (out of reach for a laptop);
  small/medium fits an 8–16 GB consumer GPU with real gains (−2.2 WER multilingual;
  larger for atypical speech with ~1.4 h of data). CPU-only training is impractical
  as of 2026. Worth watching: zeroth-order fine-tuning approaches (arXiv 2512.01267).
- An evidence-backed ordering of personalization ROI: (1) decode-time biasing lists,
  (2) corpus-mined prompt/vocabulary, (3) post-hoc correction from stored history,
  (4) LoRA fine-tuning last, reserved for GPU-equipped users with atypical speech or
  heavy domain jargon.

## Recommendations at the time of this study

- **A higher-accuracy optional engine:** Parakeet TDT 0.6B v2/v3 via `onnx-asr`
  int8 — better WER than large-v3 at roughly 4x whisper-small CPU speed, and it
  removes the class of hallucinated tokens on silent audio at the source. Fits a
  batch-per-burst pipeline well.
- **A streaming engine for live preview:** Moonshine v2 Small/Medium Streaming
  (MIT, ONNX/sherpa-onnx) as a modern replacement for LocalAgreement-style
  re-decoding. Kyutai worth watching for its built-in semantic VAD.
- **Post-processing:** two presets — a small/fast model for sub-second cleanup on
  any CPU, and a larger model for quality — plus GBNF-constrained structured edit
  operations for voice-driven text edits.

### What this study fed into

This study, together with [the gaze/EMG/BCI SoA](2026-08-07-hci-input-sota.md) and a
full codebase reachability audit, was the direct research input to
[ADR-v2-129](../../adr/adr-v2-129-killer-features-10x.md), which added the pluggable
`SttEngine` protocol and the Parakeet backend (item 2.2 there). The `stt/factory.py`
Protocol seam and `[stt] engine = whisper | parakeet` configuration described in
[`architecture.md`](../../architecture.md) are the shipped result of recommendation
1 above.
