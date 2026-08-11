# Spec: Prosody Ink — prosody-driven text formatting

| Field | Value |
|---|---|
| **ID** | spec-prosody-ink |
| **Status** | Proposed |
| **Date** | 2026-06-14 |
| **Module** | `src/yazses/postprocess/prosody.py` (new) |
| **Vision card** | the Prosody Ink vision card (internal) |
| **Maturity** | Experimental (ship pause→¶ + stress→bold; pitch→question gated) |

---

## Context

YazSes transcribes a hold-to-talk burst to plain text and injects it. The prosodic channel of speech — *where the speaker leaned in, where they paused, how the pitch moved* — is discarded at the ASR boundary, so the written output is a flat token stream. Users who want emphasis or paragraph structure must currently speak markup ("bold", "new paragraph") or leave the dictation flow to use the keyboard.

Two facts make a thin prosody-to-formatting layer feasible **on-device, on CPU**, today:

1. **Pause** is recoverable for free. faster-whisper can emit per-word timestamps (`word_timestamps=True`); the inter-word gap is a direct, CPU-trivial pause signal [doc:faster-whisper, tier4, A].
2. **Prominence (stress)** is recoverable from **~5 cheap acoustic features** — F0, RMS, loudness, voicing, HNR — at **87.5–88.7%** word-level accuracy (CNN), **84% / 0.86 F** unsupervised [paper:arXiv2104.05488, tier1, B]. These features extract faster-than-real-time with parselmouth/openSMILE.

By contrast, **rising-pitch → "?"** is unreliable: WH-questions carry *falling* F0, and pure-prosody statement/question classification sits at **~64.6%** [paper:PMC2631211, tier2, B]. Question marks are far better restored from text — text-only punctuation restoration reaches **F1 0.890** for "?" [paper:HF-FullStop, tier1, A]. So pitch→question must be experimental and must defer to the text path.

The required inputs already exist in one process: the recorded mono `float32` numpy buffer (`audio/recorder.py`) and the Whisper output (`stt/faster_whisper.py`). The integration point is the postprocess stage, immediately after `clean_text` and before injection (`core/daemon.py::_on_hold_end`).

**Open problem (carried forward honestly):** no published model demonstrates CPU-real-time word-level prominence; the strong numbers come from GPU training [paper:arXiv2508.04814, tier1, A] or untimed feature sets [paper:arXiv2104.05488]. Therefore latency must be **measured**, the whole feature must be **optional and off by default**, and a slow prosody pass must never regress the core dictation path.

---

## Decision

Add a new postprocess module `src/yazses/postprocess/prosody.py` that takes the **recorded numpy audio buffer** plus **Whisper word timestamps** and emits an annotated text string with formatting markers. It runs after `clean_text`, before classification/injection, only when `[prosody] enabled = true`.

### Scope split (deliberate, evidence-grounded)

| Sub-feature | Ships in this spec? | Basis |
|---|---|---|
| **pause → paragraph break** | **Yes (default behaviour when enabled)** | Word timestamps; CPU-trivial; whitespace renders everywhere [doc:faster-whisper] |
| **stress → bold/emphasis** | **Yes (when enabled + a renderable format is set)** | 5-feature prominence at 87–88% [paper:arXiv2104.05488] |
| **rising-pitch → "?"** | **No — gated behind `experimental_pitch_question`, off, never overrides text** | ~64.6%, WH inverts contour [paper:PMC2631211] |

### Pipeline placement

```
faster-whisper (word_timestamps=True)
  → clean_text                       (postprocess/cleaner.py)
  → prosody.annotate(audio, words)   (postprocess/prosody.py)   ← NEW, when [prosody] enabled
  → grammar.classify() / disfluency / continuation spacing
  → inject
```

Prosody runs **only on dictation** (it is meaningless for command intents) and only on the **batch** transcribe path (not the streaming partial path, which has no settled word timing). When streaming is enabled, prosody is skipped and a one-line INFO is logged.

### Module interface

```python
# src/yazses/postprocess/prosody.py
from dataclasses import dataclass
import numpy as np

@dataclass(frozen=True)
class Word:
    text: str
    start: float   # seconds, from faster-whisper word timestamps
    end: float

@dataclass(frozen=True)
class ProsodyResult:
    text: str                 # formatted text (markers per the active format)
    paragraph_breaks: int     # diagnostics, metadata-only logging
    emphasized: int
    latency_ms: float

def annotate(
    audio: np.ndarray,
    sample_rate: int,
    words: list[Word],
    config: "ProsodyConfig",
) -> ProsodyResult: ...
```

`annotate` is pure (no I/O, no daemon state). It:

1. **Pause pass** — for each adjacent word pair, if `words[i+1].start - words[i].end >= pause_paragraph_ms/1000`, insert a paragraph break (`format`-dependent marker; see below).
2. **Prominence pass** *(only if a renderable `format` is set and prominence is enabled)* — slice the audio for each word's `[start, end]`, extract the 5 features (F0, RMS, loudness, voicing, HNR) via parselmouth, score prominence, and wrap words above `emphasis_sensitivity` in the format's emphasis markers. Bias for **precision over recall** — a wrong bold is worse than a missing one (vision card §8).
3. **Question pass** *(only if `experimental_pitch_question = true`)* — compute terminal F0 slope on the last word of each sentence; may *suggest* a "?" but must **defer to** any "?" the text path already produced and never replace existing terminal punctuation. Off by default.
4. Stamp `latency_ms` for the latency-gate (see Phasing) and metadata-only logging.

### Injection-format strategy

Target apps differ — a Markdown editor, a rich-text field, and a terminal have no common "bold". A config switch selects how markers are emitted:

| `prosody.format` | paragraph break | emphasis | When to use |
|---|---|---|---|
| `none` *(default)* | `\n\n` (whitespace, universal) | **dropped** (no emphasis emitted) | Plain-text targets; safe everywhere |
| `markdown` | `\n\n` | `**word**` | Markdown editors, chat, notes apps that render MD |

`format = none` still gives pause→¶ (paragraph breaks are plain whitespace and render anywhere); it simply suppresses emphasis because there is no portable way to express it. This keeps the *safe* signal universal and confines the *app-dependent* signal to where it renders. The enum is extensible (e.g. a future `richtext` clipboard-with-formatting strategy or per-app bold keystrokes) without changing the module interface.

### Required change to the STT engine call

`FasterWhisperEngine.transcribe` currently joins segment text and discards timing. To feed prosody, the engine must expose word timestamps when prosody is enabled. Add an opt-in path (e.g. a `with_words: bool` parameter or a sibling `transcribe_words()` method) that calls `self._model.transcribe(audio, word_timestamps=True, ...)` and returns `(text, list[Word])`. When `[prosody] enabled = false`, the existing fast path is used unchanged — `word_timestamps=True` carries a small decode cost that non-prosody users should not pay.

---

## Rationale

**Ship the evidenced subset, gate the unevidenced one.** Pause→¶ and stress→bold each have peer-reviewed support and a CPU-cheap mechanism; pitch→"?" is contradicted by its own best source (~64.6%, WH falling [paper:PMC2631211]). Mixing them would let the weak signal corrupt trust in the strong ones. The flag wall is the honest boundary.

**Reuse the buffer and timestamps we already own.** The audio is already in memory as a numpy buffer and the words are one Whisper flag away — prosody is a postprocess function, not a new subsystem. This mirrors the EMG ADR's "duck-typed drop-in, no daemon redesign" discipline (ADR-v04-003).

**Off by default, latency-gated, never on the hot path of non-users.** The open problem is the absence of a demonstrated CPU-real-time prominence model. So the feature is opt-in, the extra `word_timestamps` cost is only paid when enabled, and `annotate` measures and reports its own latency so a regression is observable and can auto-degrade to pause-only.

**Precision-biased emphasis.** Per the vision card's aesthetic (§8) and SoA limit (§4), a spurious bold is more harmful than a missed one; the sensitivity default leans conservative.

---

## Alternatives Considered

| Alternative | Reason rejected |
|---|---|
| **Text-only formatting (let the punctuation/casing model handle structure)** | Recovers sentence ends and "?" well [paper:HF-FullStop] but cannot express *emphasis* or speaker-intended paragraphing — it throws away exactly the prosodic signal this feature exists to capture. Used *complementarily* for "?", not as a replacement. |
| **wav2vec2-base prominence model (F1 0.90)** | Highest accuracy [paper:arXiv2508.04814] but trained on 3×V100, no CPU/latency figures — violates the CPU-only, latency-gated constraint. The 5-feature path is the deployable one. |
| **Always emit Markdown** | Breaks plain-text and terminal targets (literal `**` characters injected). The `format` switch with a `none` default is the safe baseline. |
| **Ship pitch→"?" on by default** | ~64.6% accuracy and WH-question contour inversion [paper:PMC2631211] would inject wrong question marks. Gated and text-deferring instead. |
| **Run prosody inside the streaming partial path** | Streaming word timing is unsettled and corrections-on-commit would fight marker placement. Batch-only for now. |

---

## Configuration

New `[prosody]` section. **Off by default** — zero behaviour change unless explicitly enabled.

```python
@dataclass
class ProsodyConfig:
    """Prosody Ink — map vocal prosody to text formatting (experimental).

    OFF by default. When enabled, inserts paragraph breaks on long pauses and
    (for renderable formats) bold on stressed words, derived on-device from the
    recorded audio + Whisper word timestamps. No data leaves the machine.
    """
    enabled: bool = False
    # Output strategy. "none" => paragraph breaks only (plain whitespace, safe
    # everywhere); emphasis is suppressed. "markdown" => **bold** + blank-line ¶.
    format: str = "none"                 # none | markdown
    # Inter-word gap (ms) at/above which a paragraph break is inserted.
    pause_paragraph_ms: int = 700
    # Emphasis on/off and prominence threshold (0..1; higher = fewer, surer bolds).
    emphasis_enabled: bool = True
    emphasis_sensitivity: float = 0.65
    # EXPERIMENTAL — prosodic question detection is unreliable (~64.6%, WH-Q fall;
    # PMC2631211). OFF; only suggests "?", defers to the text path, never overrides.
    experimental_pitch_question: bool = False
    # Latency safety valve: if a prosody pass exceeds this, log a warning and
    # auto-degrade to pause-only for the rest of the session.
    max_latency_ms: int = 150
```

Wired into `config.py` exactly like the existing sections: a `prosody: ProsodyConfig` field on `Config`, constructed via `ProsodyConfig(**data.get("prosody", {}))` in `load_config`.

Example `config.toml`:

```toml
[prosody]
enabled = true
format = "markdown"        # none | markdown
pause_paragraph_ms = 700
emphasis_enabled = true
emphasis_sensitivity = 0.65
experimental_pitch_question = false   # leave off; acoustically unreliable
max_latency_ms = 150
```

---

## Dependencies

Optional dep group `prosody` in `pyproject.toml` (latest stable at time of writing). Not imported unless `[prosody] enabled = true`.

```toml
[project.optional-dependencies]
prosody = [
  "praat-parselmouth >= 0.4.6",   # Praat F0 / intensity / HNR from Python
  # numpy is already a core dependency
]
```

Install: `uv sync --extra prosody`.

- **praat-parselmouth** provides F0, intensity (RMS/loudness proxy), voicing fraction, and HNR — the exact 5-feature set in [paper:arXiv2104.05488]. Preferred over `opensmile` for a lighter install and no native-build surprises; `opensmile` (GeMAPS/ComParE wheels) is the documented fallback if parselmouth's HNR/F0 prove too coarse.
- Pause→¶ alone needs **no** new dependency (timestamps + numpy only) — important because Phase 1 ships before any acoustic dep is added.

`yazses doctor` should report whether the `prosody` extra is importable when `[prosody] enabled = true` (mirrors the EMG serial-port check in ADR-v04-003).

---

## Open problem (explicit)

There is **no demonstrated CPU-real-time word-level prominence model** in the literature; accuracy figures are GPU-trained [paper:arXiv2508.04814] or report no latency [paper:arXiv2104.05488]. Consequences for this design:

- The feature is **optional and off by default**.
- `annotate` **measures and returns** `latency_ms`; exceeding `max_latency_ms` logs a warning and auto-degrades to **pause-only** for the session.
- The cost of `word_timestamps=True` is paid **only** by users who enable prosody.
- Phase 2 (stress→bold) does not merge until measured p95 latency on a 4-core CPU clears the kill criterion in the vision card's LOFA-1 (≤150 ms added p95 on a 5 s utterance).

---

## Phased plan

| Phase | Deliverable | Gate to proceed |
|---|---|---|
| **1 — pause→¶, no acoustic dep** | `prosody.py` with the pause pass + `format`; engine word-timestamp path; `ProsodyConfig`; wiring in `_on_hold_end` (dictation, batch only). | Pause breaks land correctly; added latency negligible (timestamps already computed). |
| **2 — stress→bold** | Parselmouth 5-feature extractor + prominence scorer + emphasis markers (markdown format). | **Measured p95 latency ≤ `max_latency_ms`** on target CPU (LOFA-1); own-voice agreement ≥80% (LOFA-3). Else ship Phase 1 only. |
| **3 — experimental pitch→? (flagged, dark)** | Terminal-F0 slope question *suggestion* behind `experimental_pitch_question`, deferring to text. | Stays flagged regardless; promote only if it beats text-only "?" F1 (LOFA-4) — not expected. |
| **4 — format extensibility** | Additional `format` strategies (e.g. richtext clipboard) if real targets demand them (LOFA-5). | Driven by where users actually dictate. |

---

## Testing approach

- **Pure-function unit tests** (no audio device, no model). `annotate` takes synthetic `audio: np.ndarray` + a `list[Word]`, so:
  - **Pause pass:** fabricate word lists with gaps below/at/above `pause_paragraph_ms`; assert paragraph-break count and placement; assert no break at the start/end; assert `format = none` still emits `\n\n`.
  - **Emphasis pass:** with `format = none`, assert **no** emphasis markers emitted regardless of prominence; with `format = markdown`, feed audio slices crafted (or mocked at the feature-extractor boundary, via the `mocker` fixture) to score above/below `emphasis_sensitivity`; assert only above-threshold words are wrapped; assert precision bias (a borderline word is *not* bolded).
  - **Question pass:** default-off ⇒ never emits "?"; flagged-on ⇒ never overrides an existing terminal "?" or other terminal punctuation; only *adds* where none exists.
  - **Latency gate:** force `latency_ms > max_latency_ms` (mock the clock) and assert auto-degrade to pause-only.
- **Engine path test:** `transcribe_words()` returns aligned `Word`s; `enabled = false` leaves the existing `transcribe` fast path byte-for-byte unchanged.
- **Daemon integration test:** with `[prosody] enabled`, a dictation burst flows clean_text → prosody → inject; a **command** intent bypasses prosody; **streaming** mode skips prosody with the documented log line.
- **No new STT dep in CI for Phase 1**; Phase 2 tests mock the parselmouth feature extractor so CI does not require the `prosody` extra (mirrors how the EMG tests avoid requiring a serial device).
- **Latency benchmark (manual / opt-in):** a script over ~50 recorded utterances reporting added p95 — the evidence for the Phase 2 gate. Metadata only; honours ADR-011 (no transcript persistence).

---

## Consequences

- **One new optional dep group** (`prosody` → `praat-parselmouth`), imported only when enabled. Phase 1 (pause→¶) needs no new dep.
- **STT engine gains an opt-in word-timestamp path.** The default fast path is unchanged; the extra decode cost is paid only by prosody users.
- **App-dependent output.** Emphasis only renders where `format` matches the target (Markdown). `format = none` is the safe default — paragraph breaks (whitespace) work everywhere, emphasis is suppressed. Misconfiguring `format = markdown` in a plain-text target injects literal `**`; documented as a config caveat, not auto-detected in v1.
- **Batch-only, dictation-only.** No prosody on command intents or the streaming partial path.
- **Pitch→question is intentionally crippled by default** — it only suggests, never overrides, and is off. This is a feature, not a limitation: it prevents the unreliable acoustic signal (~64.6% [paper:PMC2631211]) from injecting wrong punctuation.
- **Latency is observable and self-limiting** — the `max_latency_ms` valve means a slow prosody pass degrades gracefully to pause-only instead of slowing every dictation.
- **Privacy unchanged.** Pure on-device postprocess over already-captured audio; nothing new leaves the machine (consistent with ADR-011).

---

### Evidence tags
`[paper:arXiv2104.05488]` 5-feature prominence (CNN 87.5–88.7%, k-means 84%/0.86F), tier1, B · `[paper:arXiv2508.04814]` wav2vec2 prominence F1 0.90 (GPU, no CPU latency), tier1, A · `[paper:PMC2631211]` prosody statement/question ~64.6%, WH falling, tier2, B · `[paper:HF-FullStop]` text-only punctuation, "?" F1 0.890, tier1, A · `[doc:faster-whisper]` word timestamps, tier4, A · `[observed:codebase]` recorder buffer, engine, postprocess slot, config pattern.
