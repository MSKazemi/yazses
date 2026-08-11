# YazSes v2 — Perceptual & Personalization Layer · Technical Roadmap

> **Status:** Planning (Phase 2 of the v2 program). **Date:** 2026-06-19.
> **Baseline:** v1.0.0 (Part 1, Python). **Audience:** contributors / implementer.
> **Sources:** the 2026-06-14 SoA dossier (internal),
> the per-feature specs (`design/specs/`), and a 2026-06-19 web refresh (citations inline).

This roadmap covers the **four remaining v2 features** — the ones that move YazSes
from a *text* tool to a *perceptual + personalized* one. They are deliberately the
hardest of the original ten: each needs an external model, training, or sensor that
the previous six did not. The other six (Say-Macro, Mid-Thought Undo, Punch-In,
Prosody Ink, Ghost Ahead, Read-Back Loop) shipped in v0.6.0–v1.0.0.

| # | Feature | What it does | Build tier | Gating resource |
|---|---|---|---|---|
| 1 | **Voiceprint Mind** | Personalizes STT to *your* voice (accent, vocabulary) | **A** — biasing now, LoRA next | a LoRA train→merge→CT2 pipeline + compute |
| 2 | **Cocktail Filter** | Ignores other voices in the room (target-speaker only) | **A** — gate now, suppress later | a voiceprint + a small target-speaker model |
| 3 | **Glance-Type** | Look at a pane/region to target where dictation lands | **C** — coarse "look-to-pane" only | a webcam + L2CS-Net/MediaPipe |
| 4 | **Polyglot Switch** | Transcribe code-switched speech (two languages mixed) | **B** — one configured pair | a trained per-pair adapter + CS corpus |

**Tiers:** A = ship a safe subset now, gate the hard part · B = needs training before
it works · C = re-scoped to what the sensor can actually do.

---

## 1. Design invariants (every feature obeys these)

Carried from v1.0.0 — non-negotiable, enforced in review:

1. **Off by default, fully local (ADR-011).** No feature changes behaviour or
   downloads a model unless explicitly enabled. Zero telemetry; nothing leaves the
   machine. Open weights only (Apache-2.0 / MIT / permissive); no GPL or
   non-redistributable weights ship as defaults.
2. **Optional-extra dependency pattern (ADR-v04-003).** Heavy deps live in a
   `pyproject` extra (like `tts`, `prosody`, `overlay`), imported only when enabled.
   A `build_*()` factory returns `None` when dormant and a `Null*` backend when
   enabled-but-unavailable — the daemon never crashes, it degrades and logs.
3. **Protocol-backed, duck-typed integration.** Each feature is a backend behind a
   `Protocol` (cf. `TtsBackend`, `HotkeyBackend`), wired at one insertion point in
   `core/daemon.py`. No pipeline redesign.
4. **TDD with a mock at the model boundary.** Model/sensor-dependent code is tested
   with a fake backend (cf. `FakeTtsBackend`); the real model is verified only on
   hardware. CI never requires a heavy dep.
5. **A pre-registered kill criterion (LOFA).** Each feature ships only if it clears
   a measurable gate on real hardware; otherwise it degrades to the documented
   fallback (cf. Read-Back's TTFA<300 ms gate, Ghost Ahead's pivot).

---

## 2. Shared infrastructure to build first (unblocks features 1 & 2)

Two features (Voiceprint Mind, Cocktail Filter) both need a **speaker voiceprint**
(a d-vector / speaker embedding from a short enrollment). Build this once, reuse twice.

### 2.1 `src/yazses/voiceprint/` (new) — speaker enrollment + embedding
- **Enrollment:** record ~20–30 s of the user's speech (reuse `accessibility/enroll.py`
  + the recorder), compute a speaker embedding.
- **Embedder:** a small open speaker-encoder — candidates: `speechbrain` ECAPA-TDNN
  (Apache-2.0, ~20 MB, CPU-runnable) or `resemblyzer` (d-vector). Behind a
  `voiceprint` extra.
- **Storage:** the embedding is personal data → store in the existing **encrypted**
  learning corpus (`learning/crypto.py`, ADR-012), machine-bound key. Never plaintext.
- **API:** `VoiceprintEnroller.enroll() -> Embedding`, `load_voiceprint() -> Embedding | None`.
- **Verifiable in-env:** embedding math, storage/crypto, enroll flow with a fake
  recorder. **Needs hardware:** real mic enrollment quality.

This module is the prerequisite for §3.1 and §3.2. **Build it first.**

---

## 3. Per-feature plans (summary; full plans in the sibling docs)

### 3.1 Voiceprint Mind — personalize STT to the user [`01-voiceprint-mind.md`]
**SoA (2026):** LoRA/PEFT Whisper fine-tune is mature (peft + 🤗 transformers);
adapter <1% params (~60 MB); on-device studies show **−44% WER** (25.1→17.7%)
[dossier; HF fine-tune-whisper]. **Critical constraint:** faster-whisper runs
CTranslate2, which cannot load a LoRA adapter live — the adapter must be **merged
into the base model and converted with `ct2-transformers-converter`**, then swapped
in [web:medium/balaragavesh, 2026]. So personalization is a *batch* process, not live.

**Build phases:**
- **P1 (buildable now, no training):** biasing layer — feed the user's vocabulary +
  recent-corpus n-grams into `initial_prompt` (the `[stt] initial_prompt` path +
  `LspContextProvider` already exist; `yazses tune` already proposes vocabulary).
  Wire a `voiceprint`-aware prompt builder. **−WER for jargon/proper nouns, zero cost.**
- **P2 (gated, needs compute):** an opt-in **nightly LoRA pipeline** — train a LoRA
  on the encrypted corpus (audio + ground-truth from `tune`'s larger-model
  re-transcription), merge, `ct2`-convert, and atomically swap the active model.
  `yazses tune --lora`. Training is ~hours; runs as a scheduled background job, never
  live. **Verifiable in-env:** the prompt builder, the pipeline orchestration (mocked
  trainer/converter). **Needs compute:** the actual LoRA train + a WER eval gate
  (ship only if eval-set WER improves on held-out data — reuse ADR-014 held-out logic).

### 3.2 Cocktail Filter — ignore other voices [`02-cocktail-filter.md`]
**SoA (2026):** VoiceFilter-Lite (2.2 MB, 8-bit, streaming, **−25% WER** multi-talker)
is the exact feature but Google-internal; the open third-party impl
(`mindslab-ai/voicefilter`) exists with **no official pretrained weights** and isn't
a pip package [web:google speaker-id; github]. Personal-VAD (130K params,
speaker-conditioned per-frame target/non-target) is the cheaper, buildable gate
[dossier].

**Build phases:**
- **P1 (buildable now):** a **personal-VAD gate** — given the §2.1 voiceprint, score
  each frame target vs non-target and *drop* non-target audio before STT (extends the
  existing `vad_calibrated.py` gate). When the room has one other voice, this prevents
  the interferer's words from entering the transcript. Reuses enrollment; trivial CPU.
- **P2 (gated, needs a model):** VoiceFilter-Lite-style **suppression** (mask the
  interferer rather than gate) — requires vendoring/adapting an impl + a trained or
  released model. Ships only when an open, CPU-real-time, permissively-licensed model
  exists. **Verifiable in-env:** the gate logic with synthetic single/multi-talker
  numpy fixtures + a fake embedder. **Needs hardware:** real multi-talker audio for the
  WER-improvement gate.

### 3.3 Glance-Type — look to target a region [`03-glance-type.md`]
**SoA (2026):** L2CS-Net **is pip-installable** (Ahmednull/L2CS-Net, pretrained
ResNet, `Pipeline` over `cv2.VideoCapture`); MediaPipe FaceMesh/Iris for landmarks.
Accuracy is **coarse** (~3–5 cm, ~3.2° still-head, degrading to ~5°/80 mm with head
motion) — **good enough for "which pane/region", not "which character"** [web:github
Ahmednull/L2CS-Net; dossier PMC11019238].

**Build phases (re-scoped to coarse):**
- **P1:** **look-to-pane** — divide the screen into N coarse zones (e.g. editor / browser
  / terminal, or a 3×3 grid); a gaze estimate selects the zone; on hold-to-talk, the
  injection targets the window under the gaze zone (reuse the window detector). Gaze
  behind a `gaze` extra (`l2cs-net`, `mediapipe`, `opencv-python`). Off by default;
  needs a webcam + a short calibration. **Verifiable in-env:** the gaze→zone mapping,
  calibration math, zone→window routing (mocked gaze + fake windows). **Needs
  hardware:** a webcam for real gaze (the user has one → on-machine validation).
- **Not built:** look-to-caret (sub-character) — the sensor can't; pre-registered as
  out of scope until webcam gaze hits <1 cm.

### 3.4 Polyglot Switch — transcribe mixed-language speech [`04-polyglot-switch.md`]
**SoA (2026):** stock Whisper **cannot** code-switch (one language per 30 s window;
"failed to produce any code-switched words"). The working approaches are **PEFT/LoRA
per-language adapters + an attention-guided LID loss** or **soft-prompt tuning** —
all require **training on a code-switch corpus** [web:arXiv2412.16507, 2506.21576,
2506.00291]. Per-pair MER ~14% (ZH-EN), per-span LID 98%+ [dossier].

**Build phases:**
- **P0 (now):** the **scaffolding** — a `[polyglot]` config for one configured language
  pair, a per-span LID hook, and an adapter-swap mechanism (slots a CS-adapted model in
  for the configured pair). No adapter ships yet.
- **P1 (gated, needs training):** train/obtain a per-pair adapter (start with the
  user's actual pair, e.g. **Persian–English** given the user's background), merge +
  ct2-convert (same pipeline as §3.1 P2), wire LID-gated decoding. Ships per opt-in pair
  only. **Verifiable in-env:** config, LID routing, adapter-swap plumbing (mocked).
  **Needs training:** the adapter + a CS eval set. **Highest-effort feature.**

---

## 4. Dependency / model / hardware matrix

| Feature | New extra | Key deps (permissive) | Model needed | Hardware to verify |
|---|---|---|---|---|
| Voiceprint (shared) | `voiceprint` | speechbrain *or* resemblyzer | speaker-encoder (~20 MB) | mic |
| Voiceprint Mind | `lora` | peft, transformers, ctranslate2 tools | LoRA trained on corpus | CPU/GPU for nightly train |
| Cocktail Filter | (reuses `voiceprint`) | numpy; (P2: onnxruntime) | P1 none; P2 target-speaker model | multi-talker mic |
| Glance-Type | `gaze` | l2cs-net, mediapipe, opencv-python | pretrained ResNet (bundled by l2cs) | **webcam** |
| Polyglot Switch | `polyglot` | peft, transformers, ctranslate2 tools | per-pair CS adapter (trained) | CS speech eval set |

All extras dormant unless enabled. `doctor` reports importability per enabled extra
(cf. the prosody check).

---

## 5. Build sequence (recommended)

```
v1.0.0 (done)
  └─ §2.1 voiceprint/ (shared enrollment + embedding)        ← build first
       ├─ Glance-Type P1 (look-to-pane)   ← most buildable as code; user has a webcam
       ├─ Cocktail Filter P1 (personal-VAD gate)  ← reuses voiceprint
       ├─ Voiceprint Mind P1 (biasing) + P2 pipeline scaffolding
       └─ Polyglot Switch P0 (scaffolding) → P1 (needs training)
```

Rationale: **Glance-Type P1** and **Cocktail Filter P1** are the most demonstrable
solo wins (gaze→zone and the personal-VAD gate are pure logic + a pip model/sensor the
user has). **Voiceprint Mind P1** (biasing) is nearly free and reuses existing config.
The training-dependent parts (Voiceprint Mind P2, Polyglot Switch P1) ship behind gates
once compute/data exist.

Each P1 lands as its own minor release (v1.1, v1.2, …); the training-gated parts as
they clear their WER/MER eval gates. A `2.0.0` is reserved for when the perceptual layer
(gaze + cocktail + personalization) is on-by-default-quality — not before.

---

## 6. Risk register

| Risk | Feature | Mitigation |
|---|---|---|
| No open VoiceFilter-Lite weights | Cocktail | Ship the personal-VAD **gate** (no model) as P1; suppression gated on an open model. |
| LoRA can't load live in CTranslate2 | Voiceprint Mind, Polyglot | Batch merge+convert pipeline (nightly), not live adaptation — documented, expected. |
| Webcam gaze too coarse for caret | Glance-Type | Re-scoped to **look-to-pane** with a pre-registered "not look-to-caret" bound. |
| Training needs data/compute the user lacks | Voiceprint Mind P2, Polyglot | P1 subsets need neither; the trained parts are opt-in and gated, never required. |
| Privacy: voiceprint is biometric data | Voiceprint, Cocktail | Stored only in the encrypted corpus (ADR-012); enrollment opt-in; never leaves machine. |
| Webcam = always-on camera concern | Glance-Type | Off by default; only active during hold-to-talk; frames never stored or sent (ADR-011). |

---

## 7. What gets verified where

- **In this dev environment (CI):** all config, factories, routing/mapping logic,
  pipeline orchestration, and TDD with mocked models/sensors. Every feature's
  *plumbing* is fully testable here.
- **On the user's machine (has mic + webcam):** real enrollment quality, the
  personal-VAD gate on real multi-talker audio, gaze→zone accuracy, the biasing-layer
  WER delta. These are the LOFA gates.
- **Needs compute/data we don't have here:** the LoRA / CS-adapter *training* runs and
  their WER/MER eval gates. The pipelines are built and tested with mocks; the trained
  artifacts are produced out-of-band and dropped in.

---

*Next: the four sibling plans (`01`–`04`) give the module layout, config schema, IPC,
daemon wiring, TDD plan, and phase gates per feature. Build order per §5.*
