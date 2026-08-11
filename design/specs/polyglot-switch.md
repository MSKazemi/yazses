# Spec: Polyglot Switch — Configured-Pair Code-Switching ASR

| Field | Value |
|---|---|
| **ID** | spec-polyglot-switch |
| **Status** | Proposed |
| **Date** | 2026-06-14 |
| **Module** | `src/yazses/stt/code_switch.py` (new); `src/yazses/stt/faster_whisper.py` (modified) |
| **Vision card** | the Polyglot Switch vision card (internal) |
| **SoA dossier** | the 2026-06-14 ten-feature SoA dossier (internal) (Feature 9) |
| **Verdict** | partial — buildable offline **per configured language pair** (P1 = ZH-EN); **not** an any-blend drop-in |

---

## Context

YazSes transcribes one language per utterance. `stt/faster_whisper.py` hard-codes `kwargs = {"language": "en"}` and `stt/streaming.py` decodes with `language="en"`; the engine never considers that a single utterance might contain two languages. This is not a YazSes oversight — it inherits a hard limit of the underlying model.

**Stock Whisper cannot code-switch.** Its decoder commits to a single language token per 30-second window. Fed a code-switched utterance, it transcribes the dominant language and translates, drops, or phonetically mangles the embedded spans. The analysis paper and the upstream issue agree it "failed to produce any code-switched words" — zero CS output [paper:arXiv2412.16507 + repo:whisper#49, tier2/7, B/C]. This one-language-per-window assumption is the central blocker: no amount of prompt engineering or VAD tuning makes the base model emit a second language mid-utterance.

The state of the art now supports a fix — but only a *scoped* one — on the CPU/on-device budget YazSes runs on:

- **Per-span LID** via a concatenated tokenizer hits **98%+** for two *known* languages [paper:ACL2023 via Gladia, tier2, B].
- **A PEFT/encoding-refined Whisper-small** reaches **14.0% MER** on ZH-EN (SEAME, ~101 h) with language-aware decoding vs a **58.3% baseline** — a ~4× reduction on a *small*, CPU-plausible model [paper:arXiv2412.16507v2, tier2, B].
- **Soft-prompt PEFT** competes with full fine-tuning at a fraction of trainable params, making a per-pair adapter cheap to train and small to ship [paper:arXiv2506.21576, tier2, B ⚠ verify table numbers].

What does **not** exist: a universal, any-pair, training-free offline CS model. CS speech raises WER **30–50%** vs monolingual even in strong systems [web:Gladia2026, tier5, C]. Therefore this feature is **opt-in and bound to one user-configured language pair**, off by default, honouring ADR-011 (nothing leaves the machine) and ADR-002's `STTBackend`-extensibility intent.

---

## Decision

Add an **opt-in, user-configured code-switching path** for **one language pair** to the STT stage. When `[stt] code_switch_pair` is set (e.g. `"zh-en"`), the daemon loads a pair-specific CS model instead of the monolingual `base.en`, decodes the utterance with the language assumption relaxed, **tags each output span with its detected language**, and the injector emits each span in its own orthography. When the key is empty (default), nothing changes: the existing monolingual path runs untouched.

This is **per-configured-pair**, not "any blend": the user declares the two languages they speak, and YazSes does that pair well — rather than faking every pair badly.

### Approach options

Two routes deliver the configured-pair capability. The spec carries **both**, picks a recommended P1, and defers the final choice to the §10 prototype measurement.

#### Approach A — PEFT/soft-prompt-adapted small Whisper (recommended P1)

A small Whisper (e.g. `small`/`base` multilingual) adapted on a CS corpus for the chosen pair via PEFT/soft-prompt, then converted to CPU int8 via the `faster-whisper`/CTranslate2 path. Decoded with language-aware decoding so it emits both languages within one utterance, with per-token language tags.

| Pros | Cons |
|---|---|
| Strongest evidence: 14% MER ZH-EN vs 58.3% baseline [arXiv2412.16507v2] | Requires a CS training corpus per pair (SEAME/SwitchLingua) — a per-pair build cost |
| Handles short embedded spans and tight seams (the model *is* code-switch-aware) | MER unproven under YazSes int8 quantization — must be re-measured (LOFA-1) |
| Per-token language tags fall out of the decode | Larger model than `base.en` → load/latency/memory cost (LOFA-5) |
| Soft-prompt PEFT makes the adapter small + cheap to train [arXiv2506.21576] | A new pair = a new adapter + corpus; not free to extend |

#### Approach B — per-span LID + monolingual re-decode (retraining-free fallback)

No training. Run the existing multilingual Whisper to get a first pass, run per-span LID (concatenated tokenizer / a small LID model) to segment the utterance into language spans, then **re-decode each span with the base model forced to that span's language** and concatenate.

| Pros | Cons |
|---|---|
| No CS corpus, no adapter, no training — works for any pair the base model knows | Weaker on short embedded spans and tight seams; re-segmentation is lossy |
| Reuses the existing Whisper model; small added surface | Multiple decode passes → higher latency |
| A safe fallback if Approach A fails its int8 MER kill criterion | No published 14%-MER-class result; expected closer to the +30–50% CS-WER floor [web:Gladia2026] |

**Recommended P1: Approach A** for the first pair (ZH-EN, the pair with the best public corpus, SEAME), *if and only if* the int8-quantized adapter clears the LOFA-1 MER/RTF kill bar. **Approach B is the documented fallback** if A fails quantization, and is the path for pairs that have no CS corpus.

### Per-span language tagging and injection

The CS engine returns not a single string but an ordered list of **language-tagged spans**:

```python
@dataclass
class LangSpan:
    text: str        # the transcribed span text in its own orthography
    lang: str        # ISO code, e.g. "zh" or "en"
    confidence: float

def transcribe_code_switch(audio, sample_rate, pair) -> list[LangSpan]: ...
```

The injector concatenates `span.text` for all spans (each already in its own script/orthography from the decoder) into the final injection string. Span boundaries are *internal* — the user sees one continuous typed result that simply happens to contain both languages correctly rendered. Low-confidence short spans default to the **matrix (dominant) language** to avoid spurious switches (LOFA-3).

### Where the adapter/model lives, and pair selection

- The pair model is a **separate, optional artifact**, not bundled with YazSes. It lives at `[stt] code_switch_model_path` (a CTranslate2/`faster-whisper` int8 model dir). Empty + `code_switch_pair` set with a known pair → resolve to a default per-pair path under the data dir (`<data_dir>/cs-models/<pair>/`), downloaded/placed by the user or a future `yazses` helper.
- The user **selects the pair in config** via `[stt] code_switch_pair = "zh-en"`. Empty = feature off, monolingual path unchanged. An unknown/unsupported pair is a `doctor` error, never a silent fallback to garbage.

---

## Configuration

New `[stt]` fields (added to the existing `SttConfig` dataclass in `config.py`). **OFF by default** — when `code_switch_pair` is empty the monolingual path is byte-for-byte unchanged.

```toml
[stt]
model = "base.en"                 # existing — used when code_switch_pair is empty
initial_prompt = ""               # existing
# --- Polyglot Switch (opt-in, per-pair, off by default) ---
code_switch_pair = ""             # "" = off. e.g. "zh-en" — the ONE configured pair
code_switch_model_path = ""       # path to the int8 CS model dir; "" => <data_dir>/cs-models/<pair>/
code_switch_approach = "adapter"  # "adapter" (A, recommended) | "redecode" (B, retraining-free)
code_switch_matrix_lang = ""      # dominant language for low-confidence/short spans; "" => first lang in pair
code_switch_min_span_confidence = 0.5  # below this, a span is reassigned to the matrix language
```

| Key | Type | Default | Description |
|---|---|---|---|
| `code_switch_pair` | `str` | `""` | The one configured pair, e.g. `"zh-en"`. Empty = feature off, monolingual path runs. |
| `code_switch_model_path` | `str` | `""` | Int8 CS model dir (Approach A). Empty resolves to `<data_dir>/cs-models/<pair>/`. Unused for Approach B. |
| `code_switch_approach` | `str` | `"adapter"` | `"adapter"` (A — PEFT-adapted model) or `"redecode"` (B — per-span LID + monolingual re-decode). |
| `code_switch_matrix_lang` | `str` | `""` | Dominant language for short/low-confidence spans. Empty = first language in the pair. |
| `code_switch_min_span_confidence` | `float` | `0.5` | Spans below this LID confidence are reassigned to the matrix language (suppresses spurious switches). |

`yazses doctor` reports whether `code_switch_pair` is set, whether the pair is supported, and (Approach A) whether `code_switch_model_path` resolves to a loadable int8 model — mirroring how it reports the EMG serial port and `[stt] model`.

---

## Integration points

| File | Change |
|---|---|
| `src/yazses/stt/code_switch.py` | **New.** `LangSpan`, `CodeSwitchEngine` (Approach A: adapted-model decode + per-token lang tags), `ReDecodeEngine` (Approach B: LID segment + per-span monolingual re-decode), `build_code_switch_engine(cfg) -> CodeSwitchEngine | None`. |
| `src/yazses/stt/faster_whisper.py` | Relax the hard-coded `language="en"`: when a CS engine is active, delegate to it and return tagged spans; otherwise behave exactly as today. Keep the monolingual signature intact. |
| `src/yazses/config.py` | Add the five `code_switch_*` fields to `SttConfig` (all defaulted; loading without them stays valid). |
| `src/yazses/core/daemon.py` | In `_initialize`, call `build_code_switch_engine(cfg.stt)`; returns `None` when `code_switch_pair` is empty so the hot path is a single `if cs_engine is not None` check. In the transcribe step, when active, get `list[LangSpan]`, join span text for injection, and record per-span langs in the learning event. |
| `src/yazses/inject/*` | No protocol change: the injector receives the joined string (each span already in its own orthography). Span metadata is carried for the learning corpus only, not the inject path. |
| `src/yazses/system/doctor.py` | Report CS status: pair set / pair supported / model loadable (Approach A). |
| `pyproject.toml` | New optional extra `polyglot` (see Dependencies). Not imported unless `code_switch_pair` is set. |

The `build_code_switch_engine() -> CodeSwitchEngine | None` factory mirrors `learning.capture.build_writer`: `None` when the feature is off, so YazSes is genuinely dormant (no extra model loaded, no latency cost) unless a pair is configured.

---

## Data flow

```
[setup, one-time]
  user sets [stt] code_switch_pair = "zh-en"
  (Approach A) places/downloads int8 CS model → <data_dir>/cs-models/zh-en/
  yazses doctor → confirms pair supported + model loadable

[runtime, per hold-release — only when code_switch_pair is set]
  recorder.stop → prepend_padding → is_silent_calibrated  (existing, unchanged)
   → CodeSwitchEngine.transcribe_code_switch(audio):
        Approach A: adapted int8 model decode → per-token language tags
                    → merge tokens into LangSpans
        Approach B: base decode → per-span LID segment
                    → re-decode each span forced to its language → LangSpans
   → for each span: if confidence < min_span_confidence → lang = matrix_lang
   → join span.text (each already in its own orthography) → injection string
   → inject (local) OR RemoteInjectorProxy
   → learning event records per-span langs + confidences (ADR-012, opt-in)

[when code_switch_pair == "" (default)]
  → existing monolingual faster_whisper path, byte-for-byte unchanged
```

The CS model loads once at daemon start (decrypt n/a — it is a model, not user data — but lazy-loaded only when a pair is set). Per-utterance cost is the adapted-model decode (Approach A) or the multi-pass LID+re-decode (Approach B), bounded by the int8 RTF measured in LOFA-1/LOFA-5.

---

## Phased plan

**P1 — one configured pair, Approach A (partial, evidence-backed).** Ship `CodeSwitchEngine` for **ZH-EN** (best public corpus, SEAME), Approach A: an int8-quantized PEFT-adapted small Whisper with per-token language tagging and matrix-language fallback for short spans. Gate the build behind LOFA-1 (int8 MER ≤ ~25% on held-out SEAME CS, RTF ≤ 1.0 on target CPU). If LOFA-1 fails, ship **Approach B** for ZH-EN instead (retraining-free, weaker on short spans) and document the accuracy gap.

**P2 — more pairs (per-pair cost, not per-feature).** Each additional pair (EN-ES, EN-FR, …) is its own adapter + corpus + eval, gated on corpus availability. Pairs with no CS corpus get Approach B only. The harness (config, LID, per-span injection, doctor checks) is built once in P1 and reused unchanged. Optionally, `yazses tune` (ADR-012) refines the active pair's adapter from opt-in encrypted user-pair CS clips.

**Explicitly never:** a universal "any blend of any languages" mode. §2/§4 mark it a field gap with no credible offline approach; the verdict is `watch`, not build.

---

## Dependencies

New optional extra `polyglot` in `pyproject.toml` (latest stable at time of writing; not imported unless `code_switch_pair` is set):

```toml
[project.optional-dependencies]
polyglot = [
  "faster-whisper >= 1.1.1",   # CTranslate2 int8 inference for the adapted/multilingual CS model
  "ctranslate2 >= 4.5.0",      # int8 quantization + CPU decode backend
  "fasttext-langdetect >= 1.0.5",  # Approach B: lightweight per-span LID (or a Whisper-internal LID)
]
```

Notes:
- **faster-whisper / ctranslate2** run the int8 CS model on CPU — same backend YazSes already uses for `base.en`, so no new runtime architecture.
- **fasttext-langdetect** (or an equivalent small LID) supports Approach B's per-span segmentation; Approach A gets language tags from the decoder directly and may not need it.
- **Training corpora are an external, build-time prerequisite — NOT a runtime dependency.** **SEAME** (Mandarin-English, ~101 h) and **SwitchLingua** are needed to *train* the Approach-A adapter offline; they are never installed, imported, or shipped with YazSes. The end user receives only the resulting int8 model artifact [paper:arXiv2412.16507v2; web:Gladia2026].
- The PEFT training toolchain (`peft`, `transformers`, a GPU) is a developer/build-time concern, not a user runtime dep.
- No GPU, no cloud, no new always-on dependency at runtime: the extra is installed and imported only when a pair is configured (`uv sync --extra polyglot`), exactly like the `emg` extra.

Verify each pinned lower bound against the current stable release at implementation time per the project's "latest-stable" rule.

---

## Testing approach

The CS engine surface is mockable with `pytest`/`mocker` (no model download, no GPU in CI):

- **`CodeSwitchEngine` (Approach A)** — inject a fake int8 model whose decode returns scripted tokens with language tags; assert the engine merges them into correct `LangSpan`s and that the joined injection string preserves each span's text/orthography.
- **`ReDecodeEngine` (Approach B)** — mock the LID segmenter and the base model; assert each span is re-decoded with the forced language and concatenated in order.
- **Matrix-language fallback** — feed spans with confidence below `code_switch_min_span_confidence`; assert they are reassigned to `code_switch_matrix_lang` (LOFA-3 guard).
- **Dormant path** — `build_code_switch_engine` returns `None` when `code_switch_pair == ""`; assert the monolingual `faster_whisper` path is unchanged and no CS model is loaded.
- **Config** — `SttConfig` defaults for all five new fields; `load_config` parsing of `[stt] code_switch_*`; unknown pair raises a clear `doctor`-surfaced error, not a silent fallback.
- **MER/RTF harness (offline, not CI)** — the §10 prototype script measuring int8 MER on a held-out SEAME CS split and RTF on the target CPU; reported in the vision card, gating P1, not a CI gate (no large model in CI).

Span-merge and fallback logic are deterministic and assertable without floating-point flakiness; model accuracy is validated by the offline harness, not unit tests.

---

## Risks & consequences

- **No universal model — per-pair only** [paper:arXiv2412.16507, tier2, B] — the defining constraint. Mitigated by scoping: opt-in, one configured pair, honest documentation. Consequence: every supported pair is a discrete build (adapter + corpus + eval), and unsupported pairs are a `doctor` error, never silent garbage.
- **Per-pair training cost / corpus availability** [paper:arXiv2412.16507v2; web:Gladia2026] — Approach A needs a CS corpus (SEAME for ZH-EN); many pairs have none. Mitigated by Approach B as a retraining-free fallback for corpus-less pairs, and by P2 gating each new pair on corpus availability (LOFA-4).
- **CS WER is 30–50% worse than monolingual even when it works** [web:Gladia2026, tier5, C] — the irreducible difficulty floor. Mitigated by a pre-registered MER kill bar (LOFA-1) and matrix-language fallback for low-confidence spans; users are told CS dictation is inherently noisier than monolingual.
- **Int8 MER unproven** [paper:arXiv2412.16507v2, tier2, B] — the 14% SEAME figure is pre-quantization. Mitigated by re-measuring int8 MER + RTF before any daemon wiring (LOFA-1); fall back to Approach B or shelve if it fails.
- **Load time / latency / memory** — a larger CS model than `base.en` raises startup and per-utterance cost (LOFA-5). Mitigated by keeping the feature opt-in and lazy-loaded; default `base.en` path is untouched.
- **Short-span LID errors** [paper:ACL2023 via Gladia, tier2, B] — single embedded words are the hardest to tag. Mitigated by `code_switch_min_span_confidence` + matrix-language fallback.
- **Privacy / learning capture** — if `yazses tune` later refines the adapter from user-pair CS clips, those clips are biometric/voice-sensitive. Mitigated by reusing only the existing opt-in, encrypted, machine-bound ADR-012 store; never auto-on, never leaves the machine.

---

## Scope boundary (explicit)

**In scope:** an opt-in, user-configured **single language pair** (P1 = ZH-EN) transcribed with code-switching — Approach A (PEFT-adapted int8 small Whisper, recommended) or Approach B (per-span LID + monolingual re-decode, fallback) — with per-span language tagging and own-orthography injection, all CPU/on-device/offline.

**Out of scope:** a universal, any-pair, training-free code-switching model. Stock Whisper emits zero CS output [paper:arXiv2412.16507 + whisper#49, tier2/7, B/C] and no credible offline approach fills the any-pair column [web:Gladia2026]. YazSes does *your configured pair* well; it does not attempt to detect and switch among arbitrary unconfigured languages. This boundary is deliberate and matches the dossier verdict: **partial — per configured pair, never universal-offline.**

---

## Open questions (deferred)

- Approach A vs B for P1 — decided by the §10 prototype on int8 MER/RTF; A if it clears the kill bar, B otherwise.
- First pair — ZH-EN (best corpus) vs an EN-ES/EN-FR pair (thinner corpus, possibly higher user demand) — decided by overlap of corpus availability and measured user-pair demand.
- Single adapted decode (A) vs multi-pass re-decode (B) latency under YazSes's CPU budget — measured in LOFA-1/LOFA-5.
- Whether per-token language tags from the adapted decoder are reliable enough to skip a separate LID model in Approach A — measured on the prototype output.
- Whether ADR-012 can ethically capture user-pair CS clips to refine the adapter over time — only under the existing opt-in encrypted machine-bound store.
