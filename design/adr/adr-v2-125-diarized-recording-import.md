# ADR-v2-125 — Diarized Recording Import (`yazses transcribe <file>`)

**Status:** Proposed (2026-07-04) · Wave O
**Context links:** [[adr-v2-083-recording-import]] (completes it — adds decode + diarization + CLI),
[[adr-v2-074-diarized-conversation-capture]] (reuses `SpeakerLabelMap`/renderer on the file path),
[[adr-v2-019-meeting-scribe]] (reuses `merge_turns`/`format_transcript`),
[[adr-v2-027-multi-user-voiceprint]] (speaker naming), [[adr-012-self-improvement-loop]] (encrypted
embeddings), [[adr-011]] (on-device, zero telemetry), [[adr-v2-126-cloud-escalation]] (deferred cloud tier)

## Context

Wave O research (internal) — a user points YazSes at
an existing audio file (voice memo, lecture, meeting, interview) and wants an **offline** transcript with
**speaker attribution** written next to the file. Today YazSes only transcribes the live mic on the
hold-to-talk path. ADR-083 accepted `yazses transcribe <file>` and built the pure subtitle core
(`recimport/subtitles.py`) but shipped **no CLI command, no audio decode, and no diarization**; ADR-074
and ADR-019 built the pure diarization-labelling cores for the **live** path. This ADR completes and
unifies them on the **pre-recorded file** path, adding the one genuinely new tier — a diarizer backend —
and wiring the three existing pure cores together.

Research resolved the hard choices. **Diarizer:** sherpa-onnx is the only engine meeting the project's
constraints (no PyTorch, no GPU, no HF token, ~15 MB ONNX models, `pip`-installable, Apache-2.0); it runs
pyannote-segmentation-3.0 + a speaker-embedding extractor + clustering entirely on CPU via bundled ONNX
Runtime. pyannote.audio (torch + HF-token gate) and NeMo Sortformer (GPU-bound) are rejected as defaults.
**STT:** reuse the existing faster-whisper engine (same weights as live dictation), not ADR-083's
Parakeet anchor (its headline RTFx is a GPU number; CPU only via an immature community ONNX export).
**Decode:** `faster_whisper.decode_audio` (PyAV, already vendored) already decodes mp3/m4a/aac/opus/mp4/
ogg/flac/wav and resamples to 16 kHz mono float32 — **zero new dependency** for full-format coverage.
**Alignment:** faster-whisper word timestamps assigned to diarizer turns by pure-numpy max-overlap
(mirrors WhisperX), merged into per-speaker utterances. **Naming:** reuse the `voiceprint/` ECAPA infra —
mean-centroid per cluster, cosine-match enrolled speakers, but only for clusters with ≥3 s aggregated
speech (cures the repo's known sub-second-ECAPA failure) and only above a reject-biased 0.50 threshold;
unknown → "Speaker N". **Privacy:** diarization is transient by default; naming is opt-in, consent-gated,
never auto-enrolls third parties (ADR-011/012; speaker embeddings are biometric under GDPR Art. 9 / BIPA).

## Decision

Add an opt-in **Diarized Recording Import** exposed as `yazses transcribe <file>`, extending the existing
`[recimport]` section (no new competing config section). OFF by default; a CLI-only path (no daemon, IPC,
hotkey, or state-machine change).

**New module `src/yazses/recimport/` additions (pure core is dependency-free; heavy tiers lazy):**

- `recimport/pipeline.py` — `transcribe_file(path, config, *, names=None, out_format=None, engine=None,
  diarizer=None) -> TranscriptResult`. **Pure orchestration**, backends injected: decode → ASR words →
  (optional) diarize turns → align → label/name → render → write sidecar. Testable with fakes.
- `recimport/audio_io.py` — `load_audio(path) -> tuple[np.ndarray, int]` via
  `faster_whisper.decode_audio` (PyAV), with an `ffmpeg`-CLI fallback guarded by `shutil.which`.
- `recimport/align.py` — **pure numpy** `assign_words_to_turns(words, turns) -> list[Turn]`
  (max-overlap per-speaker sum + argmax, `fill_nearest` with distance cap + backchannel guard) and
  `merge_utterances(turns, max_gap=1.0)`.
- `recimport/diarizer.py` — `class SherpaDiarizer` (lazy `import sherpa_onnx`) →
  `diarize(audio, sample_rate) -> list[DiarTurn(start,end,speaker)]`; `PyannoteDiarizer` a dormant name.
- `recimport/factory.py` — `build_diarizer(config) -> Diarizer | None`, returns `None` when
  `diarize=false` or the extra is missing (mirrors `voiceprint/factory.py`).
- `recimport/naming.py` — cluster→name resolution: explicit `--names`/`--rename` > enrolled-voiceprint
  match (`voiceprint` reuse, ≥`min_speaker_seconds` and ≥`name_threshold`) > "Speaker N".

**Reuse (do not reimplement):** `stt/faster_whisper.py::transcribe_words`,
`stt/vocabulary.py::merge_initial_prompt`, `stt/filters/disfluency.py::filter_transcript`,
`recimport/subtitles.py` (`merge_word_timestamps`/`write_srt`/`write_vtt`), `diarize/labels.py`
(`SpeakerLabelMap`/`render_attributed_markdown`), `scribe/diarize.py`
(`merge_turns`/`format_transcript`), `voiceprint/{embedding,factory,profiles,store}.py`.

**Config — extend `RecimportConfig`** (`enabled=false` unchanged): add `diarize: bool = False`,
`backend: str = "sherpa"`, `max_speakers: int = 0` (0 = auto), `min_speakers: int = 0`,
`output_format: str = "txt"`, `model: str = ""` (falls back to `[stt].model`), `language: str = "en"`,
`name_from_voiceprints: bool = True`, `min_speaker_seconds: float = 3.0`, `name_threshold: float = 0.5`,
`batched: bool = True`.

**CLI** (`src/yazses/cli.py`, panel `_DICTATION`) — first `Path`-file command:
`yazses transcribe AUDIO_FILE [--format txt|md|srt|vtt|json] [--diarize/--no-diarize] [--speakers N]
[--min-speakers N] [--max-speakers N] [--names "Alice,Bob"] [--rename SPEAKER_00=Alice]... [--language en]
[--model small.en] [--out PATH]`. Default output = **speaker-tagged `.txt`** at `AUDIO_FILE.with_suffix
(".txt")`. Lazy-import backends in the function body; errors via `typer.echo(err=True)` + `typer.Exit(1)`;
progress over audio duration. Emit `Speaker N:` in txt/md, raw `SPEAKER_00` in json (lossless canonical
with word timestamps + per-word speaker); **never drop speaker labels from txt** (WhisperX's bug).

**Feature registry:** the existing `_Def("recimport", "Recording Import", …)` row gains the diarization
capability; no new toggle. **Extra:** declare a real `diarization = ["sherpa-onnx>=…"]` extra (document
`pyannote`/`onnx-asr` Parakeet as manual opt-ins, like `gaze`). **Privacy:** transient labels by default;
naming only against explicitly enrolled voiceprints; unknown/short clusters stay "Speaker N"; never
auto-enroll; ship the consent notice from research §6. **Cloud:** none here — deferred to ADR-v2-126.

## Consequences

- Completes the accepted-but-unbuilt `yazses transcribe` (ADR-083) and gives it the speaker attribution
  the live features (ADR-019/074) had only for live audio — the pure cores are shared, not duplicated.
- One new optional extra (`diarization` → sherpa-onnx, no torch/GPU/HF-token, ~15 MB); base install
  unchanged. Audio decode adds **no** dependency (PyAV rides in with faster-whisper).
- Pure `align`/`naming`/`pipeline` (with injected fakes) are fully unit-testable with **zero model
  downloads**, keeping CI green; the diarizer factory returns `None` when dormant (asserted in tests).
- CPU-only, on-device, offline (ADR-011); diarization transient, embeddings encrypted-corpus-only,
  no auto-enrollment (ADR-012) — biometric-consent-safe.
- **Caveats (carried honestly):** sherpa-onnx publishes no DER/CPU-RTF → benchmark before quoting;
  faster-whisper word timestamps drift 100–400 ms → turn boundaries are approximate on rapid exchanges
  (forced alignment deferred as an opt-in heavy extra); max-overlap drops the minority speaker in
  overlapped speech; first run downloads the ~15 MB sherpa models.
