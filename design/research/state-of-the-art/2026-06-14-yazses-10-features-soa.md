# Ten Feature Ideas — State-of-the-Art Feasibility Dossier

**Date:** 2026-06-14 · **Tier:** `design/` — public engineering research
**Companion:** [`design/v2-cognitive-layer/`](../../v2-cognitive-layer/) ·
[the killer-features 10x study](2026-08-07-killer-features-10x-study.md)

A feasibility review of ten candidate feature ideas: per-feature offline/on-device
feasibility as of 2026, "why now," and evidence grading, gathered from a live web
sweep across four parallel research streams. Tags mark evidence tier (tier 1 =
peer-reviewed/replicated, descending to tier 7 = forum discussion) and grade A–F for
argument quality. A number is reported with the conditions it was measured under;
a number without them is treated as a rumor, not a fact.

---

## Verdict table

| # | Idea | Verdict | Decisive factor / "why now" | Tier |
|---|---|---|---|---|
| 5 | Voiceprint Mind (personal voice adaptation) | ready-now (continuous learning = partial) | PEFT/LoRA (<1% of params, ~60 MB) enables an overnight personal fine-tune; on-device studies show −44% WER (25.1→17.7%) | A |
| 6 | Cocktail Filter (target-speaker gate) | ready-now (gate); full separation = partial | VoiceFilter-Lite: 2.2 MB, 8-bit, streaming, −25% WER in multi-talker audio; personal-VAD at 130K params | A |
| 4 | Read-Back Loop (spoken confirmation) | ready-now | Kokoro-82M, Apache-2.0, RTF ~0.47–0.51 on a 4-core CPU, human-like quality; chunking reaches sub-second first audio | A/B |
| 10 | Say-Macro (voice macros) | ready-now | Grammar-constrained intent classification reaches ~97%+ on-device; substrate already exists in the command grammar layer; clinical speech-recognition macro retention runs 91% | A |
| 1 | Prosody Ink (prosody-aware punctuation) | partial (ship pause→paragraph and stress→bold) | Prominence detection F1 ~0.86–0.90 from ~5 cheap CPU features; pitch-to-question-mark is unreliable; no CPU-real-time prominence model demonstrated | A/B |
| 8 | Mid-Thought Undo (spoken self-correction) | partial (ship fixed templates) | Streaming self-repair detection at ~3M parameters (93 F1) plus sub-second CPU LLM parsing; open-ended reformulation success caps at 30–55% | A |
| 3 | Punch-In (respeak-to-correct) | partial (respeak → candidates → confirm) | Edit-distance/phonetic alignment is mature and cheap; but pure respeaking corrects only ~35% of errors, and accuracy drops further on a repeated retry | A |
| 9 | Polyglot Switch (mid-sentence language switching) | partial (one configured language pair at a time) | A PEFT-adapted small Whisper model reaches 14% MER on Mandarin-English; per-span language ID reaches 98%+; stock Whisper produces zero code-switched output | B |
| 2 | Glance-Type (gaze-based targeting) | too-early for caret precision | Webcam gaze accuracy of ~3–5 cm with a still head, and calibration-heavy — supports "look-to-pane," not "look-to-caret" | A/B |
| 7 | Ghost Ahead (predictive text) | too-early; pivoted | Latency is a solved problem; content prediction is not demonstrated — even code-completion ghost text is rejected roughly two-thirds of the time; the evidence instead supports pivoting to end-of-turn (endpoint) anticipation | A |

---

## Per-idea findings

### 1. Prosody Ink — partial
- FullStop / `deepmultilingualpunctuation` (XLM-R-large): text-only punctuation
  restoration, CPU-runnable; EN F1 of 0.948 (period), 0.890 (question), 0.819
  (comma) on Europarl [tier 1, grade A]. Sets the text-only baseline a prosody layer
  would need to beat.
- A lightweight on-device punctuation+casing model (CNN+BiLSTM) runs at roughly
  1/40th the size of a comparable Transformer, 2.5× faster, with a +9% relative F1
  gain on IWSLT2011 [tier 1, grade A]. Text-only punctuation already fits a CPU
  real-time budget.
- Pitch-accent detection improves ASR: word-level prominence F1 of 0.90 on the
  BURNC corpus with a wav2vec2-base model [tier 1, grade A]. Supports a
  stress-to-bold mapping; the model was trained on 3×V100 GPUs with no reported
  CPU/latency figures, on clean broadcast news audio.
- A CNN over 5 openSMILE acoustic features (F0, RMS, loudness, voicing, HNR) reaches
  87.5–88.7% pitch-accent classification accuracy; an unsupervised k-means baseline
  reaches 84%/0.86 F1 [tier 1, grade B]. This is the realistic offline path — a small
  feature set, faster than real-time on CPU via `parselmouth`/openSMILE.
- Rising-pitch-to-question-mark mapping is the weak link: WH-questions typically
  carry *falling* F0, and pitch-contour-only classification reaches only ~64.6%
  [tier 2, grade B]. Pause-to-paragraph and stress-to-bold mappings are considerably
  safer bets than pitch-to-question.
- **Verdict:** ship pause→paragraph and prominence→bold now; treat pitch→question as
  experimental.

### 2. Glance-Type — too-early for caret precision
- L2CS-Net reports 3.92° angular error on MPIIGaze, using plain RGB input and
  available as a pip-installable package [tier 2, grade A].
- The best surveyed webcam-to-screen accuracy is ~3.2–3.3° / ~50 mm RMSE with a
  still head, degrading to 5.1° / 80 mm with head motion; dedicated Tobii hardware
  reaches 15 mm/0.9° for comparison [tier 2, grade A].
- GazeRecorder reports ~1.75 cm accuracy but needs ~30 calibration points and loses
  ~9% of samples under motion; WebGazer reports ~4.06 cm [tier 2, grade B].
- MediaPipe's Iris landmarks run at 90+ FPS on ~5% CPU but do not themselves output
  a gaze vector — a regressor has to be trained on top [tier 3, grade B].
- WebGazer runs fully client-side and self-calibrates from clicks, but is validated
  only for coarse, wide screen regions [tier 2/3, grade B].
- **Verdict:** real, but accuracy-bound — best framed as "look-to-pane" or
  "jump-to-field" targeting, not caret-precise positioning.

### 3. Punch-In — partial
- Multimodal error correction studies: respeaking corrects only 35% of errors,
  versus 87% for retyping and 82% for spelling it out, at 2.7 vs. 6.6 WPM; accuracy
  *drops* further on a repeated respeak attempt [tier 2, grade A].
- A separate study reports respeaking "often does not lead to correct recognition,"
  with multimodal correction running roughly 2× faster than unimodal [tier 2, grade
  B+].
- FastCorrect uses edit-distance token alignment to locate and splice corrected
  spans, reporting −8–14% WER at 6–9× the speed of a full re-decode [tier 3, grade
  A]. The splice mechanism itself needs no additional training.
- Phonetically-aware alignment can match a respoken span even when the words differ
  from the original [tier 3, grade B+].
- No product surveyed as of 2025–26 ships in-voice span correction; Dragon's
  "Correct <word>" plus an alternatives list remains the most mature pattern found
  [tier 5, grade C].
- **Verdict:** ship respeak → 2–3 aligned candidates (reranked by a small local
  model) → explicit confirm, with a keyboard fallback on low confidence. Do not
  auto-splice without confirmation.

### 4. Read-Back Loop — ready-now
- Kokoro-82M runs CPU-only (measured on a 4-core EPYC) at RTF 0.469 (PyTorch) /
  0.509 (ONNX), 24 kHz, human-like quality, Apache-2.0 licensed; latency scales with
  utterance length, which chunking addresses [tier 6, grade B].
- KittenTTS Nano (15M params, ~25 MB int8) and Mini (80M) are Apache-2.0 and run on
  a Raspberry Pi/phone/WASM, at lower quality than Kokoro and with no official RTF
  figure published [tier 5, grade B].
- Piper (VITS-based) reports CPU-first RTF ≈0.2 (~5× real-time); its original
  MIT-licensed repository was archived in October 2025, and the actively maintained
  fork since is GPL-3.0 [tier 6, grade C] — a licensing consideration for anyone
  adopting it.
- MeloTTS (MIT) is explicitly designed for CPU real-time use; Coqui/XTTS carries a
  more restrictive weights license and is not CPU-real-time [tier 6, grade C].
- Streaming time-to-first-audio in the 50–200 ms range is reachable, and human
  turn-taking tolerance sits around 200–300 ms — the metric to optimize is
  time-to-first-audio, not full-utterance RTF [tier 2, grade B].
- **Verdict:** ready to build. Kokoro or MeloTTS (Apache/MIT) on CPU, with
  sentence-level chunking for sub-second first audio. Avoid GPL- or
  restrictive-license alternatives.

### 5. Voiceprint Mind (personal voice adaptation) — ready-now (continuous learning = partial)
- LoRA fine-tuning of Whisper-large needs <8 GB VRAM and roughly 6–8 hours on a
  12-hour personal corpus, producing an adapter of ~60 MB (<1% of model parameters)
  [tier 4, grade C].
- On-device personalization measured a −44% relative WER reduction (25.11%→17.7%)
  on atypical speech, with gains compounding across sessions [tier 2, grade B] — a
  direct evidence basis for a "personalization compounds locally over time" design.
- Residual/PEFT adapters can personalize at <0.5% of parameters per speaker, with
  continual adaptation and no measured forgetting of the base model [tier 2, grade
  B].
- Hot-word biasing helps but is not free: rare-word WER improves from 23.7% to
  18.0% and out-of-vocabulary recall from 60% to 37.1% miss rate, but error can
  *rise* on words not in the bias list [tier 2, grade B].
- TCPGen neural biasing (the open-source WhisperBiasing project) improves user-
  vocabulary recall over a fixed 1000-word list approach [tier 2, grade B].
- Error-driven data selection (using corrections a user has already made, rather
  than random sampling) outperforms random selection for fine-tuning data [tier 2,
  grade B].
- **Verdict:** ship (a) prompt/vocabulary biasing first, since it is the cheaper and
  faster-to-ship mechanism, then (b) an opt-in, scheduled background fine-tune from
  stored correction history — "continuous" here means periodic background re-tuning,
  not live in-session learning.

### 6. Cocktail Filter (target-speaker gate) — ready-now (gate); partial (full separation)
- VoiceFilter-Lite: 2.2 MB, 8-bit, streaming, real-time on-device, reporting −25.1%
  WER in overlapping speech and −14.7% in reverberant conditions, with no measured
  harm to clean speech [tier 2/3, grade A] — a close match to the target capability,
  already in production elsewhere.
- Personal VAD models run at ~130K parameters, speaker-conditioned, producing a
  per-frame target/non-target decision [tier 2, grade A].
- Silero VAD runs at ~1–2 MB with <1 ms CPU cost per 30 ms chunk (RTF 0.004)
  [tier 3, grade B].
- TargetVoice (Interspeech 2025) is a low-latency streaming target-speaker
  extraction engine designed for CPU [tier 2, grade B].
- Short-enrollment d-vector speaker embeddings are the current standard, with the
  2025–26 trend moving toward even shorter, or enrollment-less, embeddings
  [tier 2, grade B].
- SepFormer reaches a strong 19.4 dB SI-SDRi but is too heavy for CPU real-time —
  full source separation remains a GPU-tier capability [tier 2, grade A].
- **Verdict:** ship enroll-once, then a personal-VAD-plus-Silero gate with
  VoiceFilter-Lite-style suppression — not full source separation.

### 7. Ghost Ahead (predictive text) — too-early; pivoted
- Predictive text does not reliably speed up entry in controlled studies: 33 WPM
  with prediction vs. 35 WPM with none vs. 43 WPM with autocorrect alone; best-case
  gain +2 WPM, worst-case −8 WPM [tier 2, grade A].
- Word prediction suggestions are accepted for only ~1.6% of words typed
  [tier 3/2, grade B].
- GitHub Copilot's ghost-text completions are accepted 26–35% of the time — the
  strongest precedent found — but that is for *code*, and roughly two-thirds of
  suggestions are still ignored [tier 2, grade A].
- Upcoming-*speech* prediction has been studied specifically as end-of-turn timing
  rather than content: a 25M-parameter model forecasts turn-end up to 2.56 s ahead,
  cutting measured response latency from 1195 ms to 690 ms [tier 3, grade B+].
- Sub-1B-parameter GGUF models are fast enough (<200 ms for 3–5 words) but weak at
  open-ended continuation [tier 4, grade C].
- **Verdict:** content prediction is not demonstrated to work — pivot to
  endpoint/turn anticipation (hiding latency around when the user is about to stop
  speaking), which has real supporting evidence.

### 8. Mid-Thought Undo (spoken self-correction) — partial
- "Teaching BERT to Wait": streaming disfluency detection at ~3.1M parameters
  (~35× smaller than comparable models, ~80% latency reduction), reporting
  state-of-the-art streaming F1 on Switchboard [tier 1, grade A].
- "Toward Interactive Dictation" (TERTiUS): open-ended spoken edits, where a small
  targeted model reaches 30% success at 1.3 s versus a large LLM's 55% success at
  7 s [tier 1, grade A] — the closest prior art found, and evidence that open-ended
  reformulation is a genuinely hard problem.
- Reparandum (self-correction span) removal on Switchboard reaches ~0.93 F1 but
  degrades in streaming and out-of-domain settings [tier 2, grade B].
- A 1–3B-parameter Q4-quantized local model can parse a fixed pattern like "scratch
  that, make it X" in under 1 second on CPU [tier 5, grade B].
- Dragon, macOS, and Talon all ship a "Scratch That" command, but as a fixed
  template acting on the last utterance only — not open-ended reformulation
  [tier 6, grade C].
- **Verdict:** ship the fixed "scratch that"/last-burst-delete template now; gate
  arbitrary "no, make it X" rewrites behind a confidence threshold and an undo path.

### 9. Polyglot Switch (mid-sentence language switching) — partial (one configured pair)
- Stock Whisper cannot code-switch within an utterance — one paper reports it
  "failed to produce any code-switched words" over a 30-second window [tier 2/7,
  grade B/C].
- Code-switched speech raises WER by 30–50% relative to monolingual speech in
  reported benchmarks [tier 5, grade C].
- An adapted small Whisper model reaches 14.0% MER on Mandarin-English
  code-switching (SEAME, 101 hours) via encoder refinement and language-aware
  decoding, against a 58.3% baseline [tier 2, grade B] — a small enough model to be
  CPU-plausible.
- A concatenated-tokenizer approach reaches 98%+ per-span language identification
  accuracy [tier 2, grade B].
- Soft-prompt PEFT adaptation for code-switching is reported to compete with full
  fine-tuning [tier 2, grade B; table figures not independently re-verified].
- **Verdict:** buildable offline for one explicitly configured language pair at a
  time — not an arbitrary-language "any blend" capability. Requires an adapter and
  code-switched training data (e.g. SEAME or SwitchLingua).

### 10. Say-Macro (voice macros) — ready-now
- Voice macros are the highest-retention feature in clinical speech-recognition
  software: 91% usage and 72% "very helpful" rating among continuing users
  [tier 2, grade A].
- On-device speech-to-intent on a fixed grammar reaches >99% accuracy in clean
  conditions and 97% at 9 dB SNR, on a 619-command set (Picovoice Rhino benchmark)
  [tier 4, grade B].
- `voice2json` performs offline grammar-to-{intent, slots} parsing with retraining
  in under 5 seconds [tier 4, grade B].
- Talon, Caster, and Numen all ship trigger-to-snippet or trigger-to-OS-action
  macros offline, though configuration-heavy [tier 7, grade B].
- Free-form speech recognition reports errors in ~22% of dictations in one study;
  macro expansion sidesteps misrecognition risk for the covered phrases
  [tier 2, grade B].
- **Verdict:** ready to build — the substrate (a grammar classifier feeding a
  dispatcher) already exists; the remaining work is misfire suppression via
  full-utterance context gating and an explicit macro mode.

---

## Timing synthesis

The decisive 2024–2026 shifts that move several of these from "too-early" to
"ready": (1) Apache/MIT-licensed neural TTS reaching CPU real-time (Kokoro-82M) —
unlocks Read-Back Loop; (2) PEFT/LoRA collapsing personal fine-tuning to an
overnight laptop job, with on-device −44% WER results — unlocks Voiceprint Mind;
(3) 2.2 MB quantized streaming target-speaker models already in production —
unlocks Cocktail Filter; (4) grammar-constrained intent classification at 97%+
on-device — unlocks Say-Macro. Two ideas remain genuinely field-gapped: free-form
spoken *content* prediction (Ghost Ahead) and cursor-grade uncalibrated webcam gaze
(Glance-Type) — both need a pivot or a narrower scope rather than more engineering.

## Evidence-ranked build order at the time of this study

**Tier A — highest evidence, ready to build on existing infrastructure**
1. Cocktail Filter (gate) — reuses voice-enrollment infrastructure; strong
   production precedent; trivial CPU cost.
2. Voiceprint Mind — biasing layer first, nightly fine-tuning second; extends the
   existing local learning loop.
3. Say-Macro — the grammar/dispatch substrate already existed; only misfire-gating
   remained.
4. Read-Back Loop — a clean accessibility win, unlocked by CPU-real-time TTS.

**Tier B — ship the well-evidenced sub-feature, gate the harder one**
5. Prosody Ink → pause→paragraph and stress→bold now; pitch→question experimental.
6. Mid-Thought Undo → fixed "scratch that"/last-burst delete now; open-ended
   rewrites gated.
7. Punch-In → respeak→candidates→confirm, with a keyboard fallback.
8. Polyglot Switch → one opt-in, explicitly configured language pair.

**Tier C — re-scope before building**
9. Glance-Type → "look-to-pane" coarse targeting only, not caret precision.
10. Ghost Ahead → pivot to endpoint/turn anticipation; drop content prediction.

### What shipped

See [`design/v2-cognitive-layer/`](../../v2-cognitive-layer/) and `design/adr/` for
which of these ideas were built, and in what form — several of the Tier A and Tier B
items above (Cocktail Filter, Voiceprint Mind personalization, Read-Back Loop,
Say-Macro, Polyglot Switch, Glance-Type as gaze routing, Punch-In) now have shipped,
tested implementations and their own ADRs.
