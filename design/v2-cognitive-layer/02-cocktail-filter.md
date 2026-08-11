# 02 · Cocktail Filter — ignore other voices in the room

> Implementation plan. Spec: `design/specs/cocktail-filter.md`. Roadmap: `ROADMAP.md` §3.2.
> **Build tier A** — P1 (personal-VAD gate) buildable now; P2 (suppression) gated on an open model.

## Goal
When someone else is talking nearby, keep only the *enrolled* user's speech out of the
transcript. Off by default; fully local; reuses the §2.1 voiceprint.

## Why this split
The production solution (VoiceFilter-Lite, 2.2 MB streaming, −25% WER multi-talker) is
**Google-internal**; the open third-party impl has **no official pretrained weights**
and isn't pip-installable. So full *suppression* (masking the interferer) needs a model
we don't yet have. The **personal-VAD gate** (drop frames that aren't the target
speaker) is buildable now from a 130K-param speaker-conditioned classifier and the
existing VAD, and handles the common "one other voice" case.

## Module layout
```
src/yazses/audio/
  personal_vad.py     # P1: speaker-conditioned per-frame target/non-target gate
src/yazses/separate/  # P2 (later)
  voicefilter.py      # P2: target-speaker suppression backend (Protocol + Null)
  factory.py          # build_separator(cfg) -> backend | None
```
Reuses: `voiceprint/` (§2.1) for the d-vector, `audio/vad_calibrated.py` (gate it slots beside),
`audio/recorder.py` buffer.

## Config (`[cocktail]`, off by default)
```toml
[cocktail]
enabled = false
mode = "gate"                  # gate (P1) | suppress (P2)
target_threshold = 0.6         # per-frame target-speaker score to keep a frame
min_voiceprint = true          # require an enrolled voiceprint (else dormant + warn)
```

## P1 — personal-VAD gate (buildable now)
1. Requires a voiceprint (§2.1). `personal_vad.gate(audio, embedding, cfg) -> audio`:
   frame the buffer, score each frame's similarity to the target d-vector (a tiny
   speaker-conditioned classifier or cosine-on-embeddings baseline), zero/drop frames
   below `target_threshold`, return the gated buffer.
2. Wire into `core/daemon.py::_on_hold_end` **before** STT (after VAD), when
   `[cocktail] enabled and mode == "gate"` and a voiceprint exists. If no voiceprint →
   dormant + one-line warn (don't gate blindly).
3. Metadata-only logging: % frames dropped (no transcript).
**TDD (in-env):** synthetic numpy fixtures — single-talker (target) passes through;
two-talker mix (target + interferer embeddings) drops interferer-dominant frames;
no-voiceprint → pass-through + warn; all-non-target → empty → existing "silent" discard.
Fake embedder injected. **Needs hardware:** real two-talker audio for the WER gate.

## P2 — suppression (gated on an open model)
- `separate/` backend behind a Protocol (`Separator.process(audio, embedding) -> audio`),
  `build_separator` returns `None`/`Null` per the dormancy contract. Ships **only** when
  a permissively-licensed, CPU-real-time target-speaker model exists (re-evaluate the
  VoiceFilter-Lite / 3S-TSE landscape). New `cocktail` extra (onnxruntime) at that point.
- Eval gate: WER improvement on a multi-talker set vs the P1 gate, no clean-speech harm.

## Privacy
Voiceprint is biometric → encrypted corpus only (ADR-012). Audio gated/suppressed
in-RAM; nothing stored or sent.

## Verification map
- **In-env (CI):** the gate math + daemon wiring with synthetic mixes and a fake embedder.
- **User machine:** real multi-talker WER delta (the LOFA — ship the gate if it helps and
  doesn't harm single-talker).
- **Gated on a model:** P2 suppression (no open CPU-RT weights today).

---

## Live finding (2026-06-19) — P1 gate false-rejects the user's own voice ⚠️

Tested on real hardware: the personal-VAD gate **broke dictation** — it dropped ~90%
of the *user's own* speech (a 5 s utterance → one 0.5 s window survived, or all audio
gated out). ECAPA embeddings are unreliable on 0.5 s windows: the same speaker scores
low cosine vs the enrolled voiceprint at that granularity, so any `target_threshold`
strict enough to reject *other* voices also rejects *most of the user's own*.

**Decision:** default `[cocktail] enabled = false`; do NOT ship the 0.5 s-window gate.
Revisit only with (a) 1–1.5 s windows + a much lower threshold tuned live, (b) open-set
cohort scoring rather than a fixed threshold, or (c) a real target-speaker model
(VoiceFilter-Lite class — no open CPU-RT weights today). Voice-focus is **not
production-ready offline** as built. See `[[project_cocktail_filter_lesson]]`.
