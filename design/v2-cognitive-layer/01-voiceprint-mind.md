# 01 · Voiceprint Mind — personalize STT to the user

> Implementation plan. Spec: `design/specs/voiceprint-mind.md`. Roadmap: `ROADMAP.md` §3.1.
> **Build tier A** — P1 (biasing) buildable now; P2 (nightly LoRA) gated on compute.

## Goal
Reduce WER on *this user's* voice — accent, cadence, and personal vocabulary — by
(P1) biasing the recognizer with personal context, then (P2) an opt-in nightly LoRA
personal fine-tune from the encrypted corpus. Off by default; fully local.

## Why this split
faster-whisper runs **CTranslate2**, which has **no live LoRA path** — a LoRA adapter
must be **merged into the base model and `ct2-transformers-converter`-ed** before
faster-whisper can use it. So personalization is necessarily **batch** (a scheduled
re-tune that swaps the active model), not online learning. P1 needs no training and is
nearly free; P2 is the heavyweight, gated on a held-out WER win.

## Module layout
```
src/yazses/personalize/
  __init__.py
  prompt_builder.py   # P1: build initial_prompt from vocabulary + corpus n-grams
  lora.py             # P2: train→merge→ct2-convert pipeline (orchestration)
  model_store.py      # P2: atomic active-model swap + rollback
```
Reuses: `learning/store.py` (encrypted corpus, ground-truth), `config.SttConfig.initial_prompt`,
`commands/lsp_context.py` (already feeds initial_prompt), `learning/analysis.py` (held-out eval).

## Config (`[personalize]`, off by default)
```toml
[personalize]
enabled = false
bias_from_corpus = true        # P1: mine frequent personal n-grams into initial_prompt
max_prompt_terms = 64
lora = false                   # P2 master switch (separate — training is heavy)
lora_base_model = "small.en"
lora_schedule = "manual"       # manual | nightly
lora_min_events = 200          # refuse to train below this (too little data)
lora_eval_wer_gate = 0.0       # P2 ships the new model only if held-out WER improves by >= this
```

## P1 — biasing (buildable now, no training)
1. `prompt_builder.build_prompt(cfg, corpus) -> str`: union of (a) the user vocabulary
   (`[stt] initial_prompt` / `YAZSES_VOCABULARY`) and (b) top personal n-grams mined
   from the corpus (proper nouns, jargon the user repeats). Cap at `max_prompt_terms`.
2. Wire into `core/daemon.py`: when `[personalize] enabled`, compose the batch-path
   `initial_prompt` from `build_prompt(...)` (merge with any existing prompt).
3. `yazses tune` already proposes vocabulary — extend it to also surface the mined
   n-grams as a proposal.
**TDD (in-env):** `build_prompt` dedup/cap/ordering; empty-corpus → existing prompt
unchanged; daemon batch path uses the composed prompt (fake engine asserts the kwarg).
**Gate:** measure WER delta on the user's machine; ship if neutral-or-better (no regress).

## P2 — nightly LoRA (gated, needs compute)
Pipeline (`lora.py`, all orchestration — the trainer/converter are shelled out and mocked in tests):
1. **Gather:** pull (audio, ground-truth) pairs from the corpus — ground-truth from
   `tune`'s larger-model re-transcription + user `mark-wrong` corrections.
2. **Train:** `peft` LoRA on `lora_base_model` (r≈32, alpha≈64) — out-of-band job.
3. **Merge + convert:** `merge_and_unload()` → `ct2-transformers-converter` → CT2 dir.
4. **Eval gate:** WER on a held-out slice (reuse ADR-014 held-out logic). Ship only if
   it beats the current model by `lora_eval_wer_gate`.
5. **Swap:** `model_store` atomically points the daemon at the new CT2 dir; keep the
   prior as rollback. `yazses tune --lora [--schedule nightly]`.
**TDD (in-env):** the gather/eval/swap orchestration with a mocked trainer+converter
(assert: refuses below `lora_min_events`; refuses if eval WER doesn't clear the gate;
swap is atomic + rollback restores). **Needs compute:** the real train + the WER gate.

## IPC / CLI
- `yazses personalize status` — show active model, last train, held-out WER.
- `yazses tune --lora` — run the P2 pipeline once; `--schedule nightly` installs a job.

## Privacy
Voiceprint + corpus are biometric/personal → only in the **encrypted** corpus (ADR-012),
machine-bound key. Training is local; no model or audio leaves the machine. Opt-in.

## Verification map
- **In-env (CI):** prompt builder, pipeline orchestration (mocked), eval-gate + swap logic.
- **User machine:** P1 WER delta (the LOFA — ship P1 if non-regressing).
- **Needs compute:** P2 LoRA train + held-out WER gate (ship P2 only if it clears).
