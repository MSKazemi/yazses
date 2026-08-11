# Spec: Voiceprint Mind — On-Device Personal Adaptation

| Field | Value |
|---|---|
| **Slug** | `voiceprint-mind` |
| **Status** | Proposed |
| **Date** | 2026-06-14 |
| **Extends** | ADR-012 (opt-in, local, encrypted self-improvement loop) |
| **Honours** | ADR-011 (zero telemetry, nothing leaves the machine, off by default) |
| **Modules** | `src/yazses/stt/faster_whisper.py`, `src/yazses/commands/lsp_context.py`, `src/yazses/learning/` (new `personalize.py`, `biasing.py`), `src/yazses/config.py`, `src/yazses/cli.py` |
| **Vision card** | the Voiceprint Mind vision card (internal) |

---

## Context

ADR-012 closed YazSes' feedback loop by capturing an opt-in, encrypted local corpus and letting `yazses tune` propose **config** diffs (prompts, few-shots, thresholds, filters). It deliberately stopped short of touching model weights ("tuning *prompts, few-shots, thresholds, and filters*, not model weights" — ADR-012 §Decision). That left two accuracy levers on the table that the captured corpus now makes reachable:

1. **Contextual/hot-word biasing at inference time** — training-free. faster-whisper already accepts an `initial_prompt`; the corpus already knows the user's repeatedly-corrected vocabulary (`analysis._propose_vocabulary`) and `LspContextProvider` already surfaces live editor identifiers. These signals are assembled into a config diff today, but applied only after a manual `yazses tune --apply`; they are never used as a live, per-session bias list.
2. **Parameter-efficient personal fine-tune (LoRA/PEFT)** — now a laptop-overnight, ~60 MB, <1%-param job `[doc:HF/AWS, tier4, C]`, with on-device studies showing **−44% WER (25.11→17.7%)** that compounds across sessions `[paper:arXiv2106.10259+2306.09384, tier2, B]`.

Voiceprint Mind delivers both, in two layers, reusing the ADR-012 substrate (encrypted `CorpusStore`, machine-bound `Cipher`, `mark-wrong`/edit-signal error selection, `retranscribe()` pseudo-ground-truth). It does **not** introduce true online/continuous learning — see *Out of scope*.

## Decision

Ship personal adaptation in two independently-shippable layers, both opt-in and off by default.

### Layer A — Training-free contextual / hot-word biasing (P1)

A live, per-session **bias list** drives faster-whisper's `initial_prompt` (and, where supported, hot-word biasing), sourced from:

- **Corpus vocabulary** — the repeatedly-mis-transcribed-then-corrected terms `analysis.py` already computes (`_propose_vocabulary`), promoted to a persisted, decryptable **bias lexicon** rather than waiting for a manual `tune --apply`.
- **Live editor context** — `LspContextProvider.get_context()` recent identifiers + scope chain (already wired for the `initial_prompt` path in v0.4.0).
- **(optional, P1.5) TCPGen-style neural biasing** — a tight user-vocabulary list fed through a TCPGen decoder (lift `BriansIDP/WhisperBiasing` `[repo, tier2, B]`) for cases where soft prompting is too weak to fix spelling.

New module `src/yazses/learning/biasing.py`:

- `BiasLexicon` — load/merge corpus-frequent terms + LSP-live terms into a deduplicated, frequency-ranked, length-capped list. Built from the **decrypted** corpus, held in memory only.
- `build_bias_prompt(lexicon, lsp_context, max_terms) -> str` — render the `initial_prompt` string (extends, never replaces, any user-configured `[stt] initial_prompt`).

**Cost guard (evidence-driven):** hot-word/contextual biasing lifts rare-word accuracy but *raises error on un-biased words* (rare-word WER 23.7→18.0, OOV 60→37.1, un-biased error up) `[paper:arXiv2502.11572, tier2, B]`. Therefore the bias list is **tight** (corpus-frequent ∩ recently-relevant, capped at `bias_max_terms`), and a held-out A/B is part of testing (see *Testing*).

### Layer B — Opt-in scheduled nightly LoRA/PEFT adapter (P2)

New module `src/yazses/learning/personalize.py` trains a LoRA adapter over Whisper from the encrypted corpus and applies it to the faster-whisper decode path.

1. **Sample selection (error-driven).** Select training clips from the corpus where the user signalled an error — `wrong_flag` (`mark-wrong`), inferred `edit_signal`, or large `retx_distance` — using the existing `analysis.py` signals. Error-driven selection beats random `[paper:arXiv2103.03142, tier2, B]`. Ground-truth target text = `correction_text` (mark-wrong / edit) else `retx_text` (larger-model re-transcription). Audio + targets are **decrypted in memory only**, never written to a plaintext temp file.
2. **Train.** PEFT/LoRA fine-tune over a Hugging Face `transformers` Whisper of the configured base, on CPU (or GPU if present), adapter <1% params / ~60 MB `[doc:HF/AWS, tier4, C]`.
3. **Convert.** faster-whisper runs **CTranslate2, not PyTorch** (`stt/faster_whisper.py` → `faster_whisper.WhisperModel`). The trained adapter must therefore be **merged into the base PyTorch Whisper and re-converted to a CTranslate2 int8 model** via `ct2-transformers-converter`. This round-trip is the riskiest engineering assumption (see *Phased plan* P2.0 spike).
4. **Gate (no silent regression).** Before promotion, evaluate the candidate model on a held-out slice of corpus clips. Promote only if WER improves and does not regress a general benchmark set (guards catastrophic forgetting `[paper:arXiv2212.01393, tier2, B]`). This mirrors ADR-012's human-in-the-loop / no-silent-drift principle.
5. **Apply.** On daemon start, if a promoted personal model exists and `personalization.use_adapter = true`, load it instead of the stock model. `FasterWhisperEngine.__init__` gains an optional `model_path` (a local CT2 model directory) — a minimal, backward-compatible change; absent ⇒ current behaviour.

**Scheduling.** A nightly, idle-triggered, interruptible job (reusing the daemon's existing background-thread pattern, or an OS scheduler entry created by the CLI). Skips when the corpus is below `min_corpus_hours`. The user is never blocked; a fine-tune in progress never touches the live decode path until promotion.

### Storage of adapters (encrypted, machine-bound)

Adapters and converted models live under the ADR-012 data dir, encrypted with the **same machine-bound `Cipher`** (`crypto.load_or_create_key`, AES-256-GCM, `0600` key):

```
~/.local/share/yazses/
  corpus.db, corpus.key, clips/        # existing (ADR-012)
  personal/
    adapters/<ts>.lora.enc             # encrypted LoRA weights (training output)
    models/<ts>/                       # converted CT2 int8 model (the promoted artifact)
    current -> models/<ts>             # symlink to the active promoted model
    eval.json                          # held-out WER per candidate (metadata, clear)
```

Adapter/model blobs are encrypted at rest for the same reason corpus audio is: protect against casual access and accidental cloud sync, **not** a determined local attacker (ADR-012 §Consequences trade-off carries over verbatim). The CT2 model is decrypted to a `0700` runtime dir on load (or decrypted in memory if CTranslate2 supports it); the plaintext copy lives only under the user's own `0700` data dir, never in a shared temp.

## Configuration

New `[personalization]` section (all opt-in, **off by default**, honouring ADR-011). Defaults keep the code path inert.

```python
@dataclass
class PersonalizationConfig:
    """Voiceprint Mind — on-device personal adaptation (extends ADR-012).

    OFF by default. Layer A (biasing) and Layer B (LoRA) are independently gated.
    Nothing here causes data to leave the machine.
    """
    # --- Layer A: training-free contextual / hot-word biasing ---
    biasing_enabled: bool = False        # build a bias list from corpus + LSP context
    bias_from_corpus: bool = True        # include repeatedly-corrected corpus terms
    bias_from_lsp: bool = True           # include live LspContextProvider identifiers
    bias_max_terms: int = 50             # cap the list (tight list limits un-biased error)
    tcpgen_enabled: bool = False         # P1.5 neural biasing (TCPGen); needs tcpgen extra

    # --- Layer B: opt-in scheduled nightly LoRA/PEFT adapter ---
    adapter_enabled: bool = False        # master switch for nightly fine-tune
    use_adapter: bool = True             # load a promoted personal model if present
    base_model: str = "small.en"         # HF Whisper to LoRA-tune (>= live stt.model)
    schedule: str = "nightly"            # "nightly" | "weekly" | "manual"
    min_corpus_hours: float = 1.0        # skip training below this much captured audio
    max_train_minutes: int = 240         # wall-clock budget; abort + keep prior model
    lora_rank: int = 16                  # PEFT rank (adapter size / capacity)
    promote_min_wer_gain: float = 0.03   # promote only if held-out WER drops >= this (abs)
    eval_holdout_frac: float = 0.2       # corpus fraction reserved for the promotion gate
```

`base_model` defaults to `small.en` (matches `[learning] tune_model`): a slightly larger base gives the adapter more to personalise than `tiny.en` while staying CPU-trainable overnight.

## CLI surface

Extend the existing `yazses` Typer app with a `personalize` command group (the `tune` flow stays for config-diff proposals; personalization is weight/biasing adaptation, kept distinct):

| Command | Behaviour |
|---|---|
| `yazses personalize status` | Show bias lexicon size, last train time, active model, held-out WER, corpus hours vs `min_corpus_hours`. |
| `yazses personalize bias` | Print the current Layer-A bias list (decrypted, terminal only). `--rebuild` recomputes from corpus + LSP. |
| `yazses personalize train` | Run a Layer-B fine-tune now (respects `max_train_minutes`); train → convert → eval → report. `--apply` promotes if the gate passes; without it, only reports the candidate WER. |
| `yazses personalize promote <ts>` / `revert` | Manually promote a candidate / revert to stock model. |
| `yazses personalize schedule` | Install/remove the nightly idle job (`--off` to remove). |
| `yazses personalize forget` | Delete all adapters/models (corpus untouched; use `yazses corpus destroy` for the corpus). |

Promotion is **never silent** — automatic nightly runs promote only when the held-out gate passes *and* `adapter_enabled = true`; the user can always `revert`. This preserves ADR-012's "no silent config/model drift" principle.

## Dependencies

Layer A needs **no new runtime deps** (reuses `initial_prompt`). Layer B's training stack is heavy and **must not** burden the daily-driver install — it goes in optional extras, installed only when the user opts into nightly fine-tuning. Use latest stable at implementation time:

```toml
[project.optional-dependencies]
# Layer B — personal LoRA fine-tune (heavy; install only to train adapters)
personalize = [
    "torch>=2.9",              # CPU wheel; training backend for PEFT
    "transformers>=4.57",      # HF Whisper for LoRA training
    "peft>=0.18",              # LoRA/PEFT adapters
    "accelerate>=1.12",        # training loop / device placement
    "datasets>=4.5",           # corpus -> training dataset shaping
    "ctranslate2>=4.6",        # ct2-transformers-converter (merged model -> int8)
]
# Layer A.5 — optional TCPGen neural biasing
tcpgen = ["torch>=2.9"]
```

Install with `uv sync --extra personalize`. `personalize.py` imports these lazily and degrades cleanly (clear "install the personalize extra" message) when absent — matching the `emg`/`pyserial` optional-dep pattern (ADR-v04-003 §Dependency). Pin lower bounds to current stable; bump when stale (global dependency rule).

## Honest compute / time cost

- **Layer A:** effectively free — string assembly + the `initial_prompt` decode already in the pipeline. No training, no new model load.
- **Layer B training:** the published envelope is **~6–8 h on a 12 h corpus for Whisper-large on a single GPU** `[doc:HF/AWS, tier4, C]`. On a **CPU-only laptop with `small.en`** and a *small* personal corpus the wall-clock is unknown and is gated by `max_train_minutes` (abort + keep prior model on overrun). This is **overnight, idle-time, opt-in** work, not interactive — and explicitly framed as such to users. A nightly run that can't finish in budget simply doesn't promote.
- **Disk:** adapters ~60 MB each `[doc:HF/AWS]`; converted int8 model is base-model-sized (tens–hundreds of MB). Old adapters/models pruned (keep `current` + N recent).
- **No accuracy promise without measurement:** the −44% WER figure `[paper:arXiv2306.09384, tier2, B]` is from atypical-speech research corpora, **not** a guarantee for a given user's small corpus. The promotion gate (`promote_min_wer_gain`) is what actually protects the user — if a real adapter doesn't beat stock on held-out clips, it is never promoted.

## Phased plan

- **P1 — Layer A biasing (ship first).** `biasing.py` (`BiasLexicon`, `build_bias_prompt`); wire the bias prompt into the existing `initial_prompt` path in the daemon; `[personalization]` Layer-A keys; `yazses personalize bias/status`. No new deps. Validate on held-out corpus clips.
- **P1.5 — (optional) TCPGen neural biasing.** Behind `tcpgen_enabled` + `tcpgen` extra, for spelling cases soft prompting can't fix.
- **P2.0 — Conversion spike (de-risk first).** Before any product code: prove a PyTorch Whisper LoRA can be merged and `ct2-transformers-converter`-ed to int8, load in faster-whisper, and decode at acceptable speed. **Kill criterion (pre-registered): if it won't load or decodes >2× slower than stock int8, ship Layer A only and shelve Layer B.**
- **P2 — Layer B nightly LoRA.** `personalize.py` (select → train → merge → convert → eval-gate → promote); `[personalization]` Layer-B keys; `yazses personalize train/promote/revert/schedule`; `personalize` extra; encrypted adapter/model storage; nightly idle scheduler.
- **P3 — (deferred) Rust v1.0 port.** ADR-012's Rust-port backlog item extends to the biasing layer; LoRA training likely stays a Python-side tool even in the Rust core.

## Testing approach

- **Unit (no models, no deps):** `BiasLexicon` merge/dedup/cap; `build_bias_prompt` extends rather than replaces user `initial_prompt`; sample selection picks exactly the `wrong_flag`/`edit_signal`/`retx_distance` events (inject fake `EventRecord`s, mirroring existing `analysis` tests); storage round-trips an encrypted adapter blob via `Cipher`; config defaults keep both layers inert.
- **Layer A efficacy (held-out A/B):** on a held-out corpus slice, transcribe with biasing on vs off; assert rare-word/target-term accuracy rises **and** combined (biased + un-biased) WER does not regress — the cost guard from `[paper:arXiv2502.11572, tier2, B]`.
- **Layer B integration (gated, opt-in, skipped in default CI):** behind a marker requiring the `personalize` extra — a tiny end-to-end train→merge→convert→load→decode on a tiny fixture corpus, asserting the CT2 model loads and the promotion gate logic promotes only on WER gain. The default `pytest` run (Linux×macOS×Windows, 3.11/3.12) must not pull the heavy extra.
- **Privacy regression:** assert no plaintext audio/text/adapter is written outside the `0700` data dir during training; assert both layers are no-ops when `[personalization]` keys are at defaults; assert nothing opens a network socket (mirrors the ADR-011 CI guarantees).

## Privacy / threat-model consequences

- **Nothing leaves the machine.** Training, conversion, evaluation, and inference are all on-device. No new network egress — the same invariant ADR-012 established. The personal model *is* the user's data in distilled form and is treated as such.
- **Encrypted at rest, machine-bound key.** Adapters and converted models use the existing AES-256-GCM `Cipher` and `corpus.key` (`0600`). The ADR-012 trade-off carries over unchanged: protects against casual access and accidental sync, **not** a determined local attacker with the user's read access. Users wanting vault-grade protection keep personalization off or use full-disk encryption.
- **Off by default (ADR-011).** With `[personalization]` unset, no bias list is built, no fine-tune runs, no extra model loads — the code path is inert, exactly as ADR-012's `[learning] enabled = false` keeps capture dormant.
- **Model-inversion surface.** A personal acoustic model can in principle leak training-speaker characteristics; since it never leaves the device and is encrypted at rest, this only matters under the same "determined local attacker" threat already documented and accepted. No new sharing/export path is provided by default; `personalize forget` removes everything.
- **No new keystroke or content capture.** Voiceprint Mind consumes only what ADR-012 already captures; it adds no new sensors or signals.

## Out of scope (explicit)

**True online / continuous learning is out of scope.** No source in the state-of-the-art sweep shows a credible CPU-real-time online weight-update for Whisper-class ASR; the live-update capability is a field gap (vision card §2 matrix, right-most column = `✗`). "Continuously adapts" therefore means a **scheduled batch re-tune** (nightly/weekly), not per-utterance learning. The product copy and CLI must say so; promising live learning would be the one claim graded **F** in the vision card's bullshit filter.

## Open questions

- Does int8 CT2 quantization erase the LoRA's accuracy gain? *Deferred — answered by the P2.0 conversion spike (run before committing Layer B).*
- Minimum corpus hours for a nightly LoRA to beat Layer A? *Deferred — calibrate `min_corpus_hours` from the first real adapter's held-out WER.*
- Bias list always-on vs per-context (code vs prose)? *Deferred — decided by the Layer-A biased/un-biased A/B.*

---
### Evidence tags
`[paper:arXiv2106.10259+2306.09384, tier2, B]` on-device personalization −44% WER · `[paper:arXiv2109.06952+2212.01393, tier2, B]` residual/PEFT continual adapters · `[paper:arXiv2502.11572, tier2, B]` hot-word biasing gain + un-biased cost · `[paper:arXiv2103.03142, tier2, B]` error-driven selection · `[repo:BriansIDP/WhisperBiasing, tier2, B]` TCPGen · `[doc:HF/AWS, tier4, C]` LoRA cost/size envelope. Full dossier: the 2026-06-14 ten-feature SoA dossier (internal) (#5).
