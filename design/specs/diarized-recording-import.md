# Spec: Diarized Recording Import — `yazses transcribe <file>`

| Field | Value |
|---|---|
| **ID** | spec-diarized-recording-import |
| **Status** | Proposed |
| **Date** | 2026-07-04 |
| **ADRs** | [[adr-v2-125-diarized-recording-import]] (completes [[adr-v2-083-recording-import]]), [[adr-v2-126-cloud-escalation]] (deferred) |
| **Research** | the diarized recording import research note (internal) |
| **Module** | `src/yazses/recimport/` (extend: `pipeline.py`, `audio_io.py`, `align.py`, `diarizer.py`, `factory.py`, `naming.py` new; `subtitles.py` reused) |
| **Maturity** | Wave O opener; OFF by default; CPU-only, offline |

---

## Context

YazSes transcribes only the live microphone. Users have archives of recordings (voice memos, lectures,
meetings, interviews) they want transcribed offline, with **who-said-what** attribution, as a text file
next to the source. ADR-083 accepted `yazses transcribe <file>` and built only the pure subtitle writers;
ADR-074/019 built pure diarization labellers for the **live** path. This spec wires those cores together
on the **pre-recorded file** path and adds the one new tier — a CPU diarizer — plus file decode and the
CLI command. Everything is OFF by default and on-device (ADR-011).

The research resolved every backend choice (see the report). The load-bearing outcomes: **sherpa-onnx**
is the only CPU-friendly diarizer meeting the no-torch/no-GPU/no-HF-token bar; **`faster_whisper.decode_
audio`** (PyAV, already vendored) decodes every common format to 16 kHz mono float32 with **zero new
dependency**; **faster-whisper word timestamps** aligned to turns by a **pure-numpy max-overlap** rule
(mirroring WhisperX) is sufficient without torch; **voiceprint naming** must be gated to ≥3 s clusters and
a reject-biased 0.50 cosine to be reliable; and **diarization is transient by default** (naming is opt-in
and consent-gated) because speaker embeddings are biometric data.

---

## Decision

Add `yazses transcribe <file>` on a **CLI-only path** (no daemon/IPC/hotkey/state-machine change),
extending the existing `[recimport]` config. Pipeline:

```
file → load_audio (PyAV decode → 16k mono f32)
     → FasterWhisperEngine.transcribe_words  (word timestamps; batched on long files)
     → [if diarize] SherpaDiarizer.diarize → turns
     → align.assign_words_to_turns → align.merge_utterances  (pure numpy)
     → naming: --names/--rename  >  enrolled voiceprint (≥3s, ≥0.50)  >  "Speaker N"
     → render (txt | md | srt | vtt | json)   (reuse subtitles.py / labels.py / scribe.diarize)
     → write sidecar  <input-stem>.<ext>
```

### Scope split (deliberate, evidence-grounded)

| Sub-feature | Ships in Wave O? | Basis |
|---|---|---|
| File decode (all common formats) → 16k mono | **Yes** | `faster_whisper.decode_audio` (PyAV), zero new dep |
| Offline ASR with word timestamps (faster-whisper) | **Yes** | reuse `transcribe_words`; `BatchedInferencePipeline` on long files (~2.6× CPU) |
| sherpa-onnx diarization + pure max-overlap alignment | **Yes (opt-in, `--diarize`)** | only CPU-fit diarizer; pure alignment mirrors WhisperX |
| Speaker naming from enrolled voiceprints | **Yes (opt-in, gated ≥3 s / ≥0.50)** | reuse `voiceprint/`; cures sub-second ECAPA failure |
| Output txt/md/srt/vtt/json | **Yes** | reuse `subtitles.py` + `labels.py`; json lossless canonical |
| **Forced alignment (wav2vec2/ctc) for <100 ms word ts** | **No — deferred opt-in heavy extra** | needs torch; word-ts drift acceptable for turns ≥1–2 s |
| **Parakeet ONNX STT option** | **No — deferred optional extra** | CPU numbers immature; turbo already covers accuracy tier |
| **Cloud escalation** | **No — deferred (ADR-126)** | audio would leave the machine; explicit opt-in only |

### Module interfaces

```python
# src/yazses/recimport/pipeline.py  — PURE orchestration (backends injected)
from dataclasses import dataclass

@dataclass(frozen=True)
class Utterance:
    speaker: str          # canonical id "speaker_0" (renderer maps to display name)
    start: float
    end: float
    text: str

@dataclass(frozen=True)
class TranscriptResult:
    utterances: list[Utterance]   # empty-speaker single utterance when diarize=False
    words: list                   # (word, start, end) for subtitle/json paths
    language: str
    diarized: bool
    speaker_names: dict           # canonical id -> display name (resolved)

def transcribe_file(path, config, *, names=None, renames=None, out_format=None,
                    engine=None, diarizer=None, embedder=None,
                    progress=None) -> TranscriptResult: ...
    # engine/diarizer/embedder default to factory-built from config when None (real run);
    # tests inject fakes. progress: optional callable(fraction) for the CLI bar.

# src/yazses/recimport/audio_io.py
def load_audio(path) -> "tuple[np.ndarray, int]": ...   # PyAV via faster_whisper.decode_audio;
                                                        # ffmpeg-CLI fallback if shutil.which("ffmpeg")

# src/yazses/recimport/align.py  — PURE numpy, no torch
def assign_words_to_turns(words, turns, *, fill_nearest_max=2.0,
                          backchannel_max=0.3) -> list: ...   # per-speaker overlap sum → argmax
def merge_utterances(assigned, *, max_gap=1.0) -> list["Utterance"]: ...

# src/yazses/recimport/diarizer.py  — heavy tier, lazy import
class SherpaDiarizer:
    def __init__(self, config): ...      # lazy `import sherpa_onnx`; loads seg + embedder models
    def diarize(self, audio, sample_rate=16000) -> list: ...   # [DiarTurn(start,end,speaker)]

# src/yazses/recimport/factory.py
def build_diarizer(config): ...          # -> Diarizer | None  (None if disabled / extra missing)

# src/yazses/recimport/naming.py
def resolve_names(utterances, config, *, names=None, renames=None, embedder=None,
                  audio=None, sample_rate=16000, profiles=None) -> dict: ...
    # precedence: explicit names/renames > enrolled voiceprint (centroid≥3s, cosine≥name_threshold)
    #             > "Speaker N".  Never auto-enrolls.  Returns canonical-id -> display-name.
```

### CLI signature (`src/yazses/cli.py`, panel `_DICTATION`)

```
yazses transcribe AUDIO_FILE
    [--format txt|md|srt|vtt|json]       # default: txt
    [--diarize / --no-diarize]           # default from [recimport] diarize (false)
    [--speakers N]                       # exact count (0/omit = auto)
    [--min-speakers N] [--max-speakers N]
    [--names "Alice,Bob"]                # positional map speaker_0=Alice, speaker_1=Bob
    [--rename speaker_0=Alice]           # repeatable, explicit
    [--language en] [--model small.en]
    [--out PATH]                         # default: AUDIO_FILE.with_suffix('.'+fmt)
```

`typer.Argument(..., exists=True, dir_okay=False)`; lazy-import backends inside the function; errors via
`typer.echo(err=True)` + `typer.Exit(1)`; progress bar over audio duration. Output: `Speaker 1:` in
txt/md, raw `SPEAKER_00` + word timestamps + per-word speaker in json. **txt always carries speaker
labels** when diarized (avoid WhisperX's documented drop bug).

---

## Configuration

Extend `RecimportConfig` (unchanged `enabled=False` gate). **Off by default** — zero behaviour change.

```python
@dataclass
class RecimportConfig:
    """Recording Import — offline batch file transcription with speaker attribution (ADR-125).
    OFF by default. Diarization is transient; naming is opt-in, consent-gated, on-device."""
    enabled: bool = False
    diarize: bool = False              # attribute speakers; false = plain transcript
    backend: str = "sherpa"            # sherpa | pyannote(dormant) | none
    max_speakers: int = 0              # 0 = auto-detect
    min_speakers: int = 0
    output_format: str = "txt"         # txt | md | srt | vtt | json
    model: str = ""                    # "" => inherit [stt] model
    language: str = "en"
    batched: bool = True               # BatchedInferencePipeline on long files
    name_from_voiceprints: bool = True # match enrolled voiceprints (needs enrollment)
    min_speaker_seconds: float = 3.0   # min aggregated cluster speech to attempt naming
    name_threshold: float = 0.5        # reject-biased cosine similarity to accept a name
```

Registered exactly like the existing sections: field on `Config`, `RecimportConfig(**data.get
("recimport", {}))` in `load_config` (already wired at `config.py:1565` — extend the dataclass only).

---

## Dependencies

New optional extra in `pyproject.toml` (latest stable at implementation time):

```toml
[project.optional-dependencies]
diarization = ["sherpa-onnx>=1.10"]     # ONNX Runtime bundled; no torch, no GPU, no HF token
```

Install: `uv sync --extra diarization`. **No decode dependency needed** — PyAV rides in with the existing
faster-whisper dep and `faster_whisper.decode_audio` handles all formats + resample. Speaker naming reuses
the existing `voiceprint` extra (speechbrain ECAPA). Parakeet ONNX STT and wav2vec2 forced alignment are
documented **manual** opt-ins (like `gaze`), not declared. `yazses doctor` should report whether the
`diarization` extra is importable when `[recimport] diarize = true`, and whether the sherpa models are
downloaded (mirror the STT-model check).

First-run model fetch: sherpa seg-3.0 (~6 MB) + ERes2Net-base int8 (~8 MB) from GitHub Releases; provide
a `yazses transcribe --download-models` affordance and a clear offline error if absent.

---

## Testing approach (CI green, zero model downloads)

- **Pure `align.py`** — synthetic `words` + `turns`: max-overlap assignment; straddling word (per-speaker
  overlap sum before argmax); zero-overlap gap → `fill_nearest` within cap, `None` beyond cap; backchannel
  guard (<0.3 s word not stolen); deterministic tie-break; `merge_utterances` breaks on speaker change and
  `max_gap`.
- **Pure `naming.py`** — precedence (explicit `--names`/`--rename` > voiceprint > "Speaker N"); cluster
  <`min_speaker_seconds` stays anonymous even with a match; match <`name_threshold` rejected; never
  enrolls. Voiceprint path uses a **fake embedder** returning canned cosine scores.
- **`pipeline.transcribe_file`** with **injected fake** engine + fake diarizer + fake embedder: end-to-end
  produces expected `Utterance`s and the correct sidecar text per format; `diarize=False` yields one
  unattributed transcript.
- **`factory.build_diarizer`** returns `None` when `diarize=false` or `sherpa_onnx` import fails (mirror
  `test_voiceprint.py`); `SherpaDiarizer.__init__` import guarded.
- **`audio_io.load_audio`** — tiny generated WAV fixture decodes to 16 k mono float32; mp3/ffmpeg paths
  `pytest.importorskip`/skip when the tool is absent.
- **CLI** — `CliRunner().invoke(cli.app, ["transcribe", tmpwav, "--diarize", ...])` with engine+diarizer
  monkeypatched (reuse the `Engine.__new__(Engine)` mock from `test_faster_whisper_words.py`); assert exit
  code, sidecar file written next to input, speaker tags present, `--help` lists all flags, `--format
  json` is lossless.
- **Render reuse** — extend existing `test_recimport_crowdproof.py` / subtitle tests to cover the
  speaker-tagged txt/md rendering via `labels.py` + `scribe/diarize.py`.

No GPU, no model download, no network in CI — pure cores + fakes carry coverage; the `diarization`/
`voiceprint` extras are import-guarded.

---

## Phased plan

| Phase | Deliverable | Gate |
|---|---|---|
| **1 — transcribe, no diarization** | `audio_io` + `pipeline` + CLI writing `<stem>.txt`/srt/vtt/json via faster-whisper (batched); `RecimportConfig` extended. | Sidecar matches a known clip; all formats write; CI green with fakes. |
| **2 — diarization + alignment** | `SherpaDiarizer` + `factory` + pure `align`; `--diarize`/`--speakers`; `Speaker N:` output. | Speaker turns land on a 2-speaker clip; **benchmark DER + CPU RTF on real audio** (unpublished upstream). |
| **3 — voiceprint naming** | `naming.py` reusing `voiceprint/`; `--names`/`--rename`; ≥3 s / ≥0.50 gates; consent notice. | Enrolled speaker auto-named; unknown/short → "Speaker N"; no auto-enroll; notice shown. |
| **4 (deferred)** | forced-alignment extra; Parakeet ONNX STT extra; cloud escalation (ADR-126). | Own waves; re-verify. |

---

## Consequences

- Completes `yazses transcribe` (ADR-083) and unifies the live diarization cores (ADR-019/074) onto the
  file path — cores shared, not duplicated.
- One new optional extra (`diarization` → sherpa-onnx); **no decode dependency** added; base install lean.
- Pure `align`/`naming`/`pipeline` fully unit-tested with fakes → CI stays green with no model downloads.
- On-device, offline (ADR-011); diarization transient, embeddings encrypted-corpus-only, no auto-enroll
  (ADR-012); biometric-consent notice shipped.
- **Honest caveats:** sherpa DER/RTF unmeasured (benchmark in Phase 2); word-ts drift 100–400 ms →
  approximate turn boundaries on rapid exchanges; overlapped speech drops the minority speaker; first run
  downloads ~15 MB of models.
