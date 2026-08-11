# 04 · Polyglot Switch — transcribe code-switched speech

> Implementation plan. Spec: `design/specs/polyglot-switch.md`. Roadmap: `ROADMAP.md` §3.4.
> **Build tier B** — needs a trained per-pair adapter before it works; scaffolding now.
> **Highest-effort feature.** Build last.

## Goal
Transcribe speech that mixes two languages mid-utterance (e.g. Persian–English) for one
**configured** language pair. Off by default; fully local.

## Why this is the hard one
Stock Whisper **cannot** code-switch — it assumes one language per 30 s window and
"failed to produce any code-switched words" [web:arXiv2412.16507]. The working
approaches all require **training**: per-language LoRA matrices + an attention-guided
**LID loss**, or **soft-prompt tuning**, on a **code-switch corpus** [web:arXiv2506.21576,
2506.00291]. Per-pair MER ~14% (ZH-EN), per-span LID 98%+ [dossier]. There is no
drop-in open CS model for an arbitrary pair — it is trained per pair.

## Module layout
```
src/yazses/polyglot/
  __init__.py
  config.py          # the configured language pair
  lid.py             # per-span language ID over the audio/partials (frame/segment LID)
  adapter_store.py   # slot a CS-adapted (merged+ct2) model for the configured pair
  decode.py          # LID-gated decoding: route spans / prompt the adapted model
```
Reuses the §3.1 (`personalize/lora.py`) **train→merge→ct2-convert** pipeline — the
adapter mechanics are identical; only the training data (a CS corpus) and the LID-gated
decode differ.

## Config (`[polyglot]`, off by default)
```toml
[polyglot]
enabled = false
pair = ""                      # e.g. "fa-en" — exactly one configured pair
adapter_path = ""              # path to the merged+ct2 CS adapter for `pair`; empty = dormant
lid = "segment"                # segment | frame — span language ID granularity
mer_gate = 0.0                 # ship the adapter only if held-out MER beats baseline by this
```

## P0 — scaffolding (buildable now, no model)
1. `config.py`: validate one `pair`; dormant unless `enabled` + `adapter_path` set.
2. `lid.py`: per-span language ID (start with Whisper's own per-segment language probs;
   later a small frame-LID). Pure-ish logic, testable on synthetic segment streams.
3. `adapter_store.py`: load the configured pair's CS-adapted CT2 model and make the STT
   engine use it when `[polyglot] enabled` (slots beside the default model).
4. `decode.py`: LID-gated decode path — when CS is configured, use the adapted model and
   keep both languages' tokens (don't force one language).
**TDD (in-env):** config validation (one pair only; dormant without `adapter_path`); LID
routing over synthetic segment probabilities; adapter-swap plumbing (mocked model);
dormant path leaves the normal pipeline byte-identical. **Needs training:** the adapter.

## P1 — the adapter (gated, needs training + a CS corpus)
- Obtain/assemble a CS corpus for the configured pair (start with the user's real pair,
  e.g. **fa-en**), train a LoRA/soft-prompt CS adapter (per the 2026 papers), merge +
  ct2-convert (the §3.1 pipeline), and wire LID-gated decoding.
- **Eval gate:** held-out MER for the pair beats the stock-Whisper baseline by `mer_gate`;
  no regression on monolingual input. Ships per opt-in pair only.

## Privacy
Adapter trained locally from local data; nothing leaves the machine. Opt-in.

## Verification map
- **In-env (CI):** config, LID routing, adapter-swap plumbing, dormant-path invariance (mocked).
- **Needs training + data:** the per-pair CS adapter and its MER eval gate — the ship gate.
- **Note:** this is the feature most likely to remain "scaffolded + 1 trained pair" rather
  than general; that's expected and documented.
