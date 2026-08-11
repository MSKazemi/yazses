# ADR-v2-127 — Live Meeting Mode (hands-free capture + hybrid diarization)

**Status:** Proposed (2026-07-10) · Wave P
**Context links:** [[adr-v2-019-meeting-scribe]] (implements it; corrects its online-Sortformer anchor),
[[adr-v2-125-diarized-recording-import]] (reuses `SherpaDiarizer`/`align`/`naming`/`render` on the live path),
[[adr-v2-074-diarized-conversation-capture]] (reuses `SpeakerLabelMap`/renderer),
[[adr-v2-028-multiuser-voiceprint-profiles]] (speaker naming), [[adr-012-self-improvement-loop]] (encrypted
biometric embeddings), [[adr-011]] (on-device, zero telemetry), [[adr-v2-128-meeting-minutes-generation]]
(notes), [[adr-v2-126-cloud-escalation]] (deferred cloud tier)

## Context

Hold-to-talk dictation cannot cover a meeting: a user cannot hold a key for an hour, and a single
key-holder cannot capture several people. The need is **start once, run hands-free, discover how many
distinct people are speaking without being told the count, label each, and produce a saved transcript
(and opt-in notes) at the end** — with the transcript visibly forming live ("online dictation, not just
recording"). ADR-v2-019 accepted an "Ambient Meeting Scribe" with pure labelling cores but anchored on
**NVIDIA Streaming Sortformer** for online diarization; it was never built.

Research (`design/meeting-mode/`, 57 cited sources) resolved the hard choices and **overturns that anchor**:

- **Speakers are separated by neural embeddings + clustering, not pitch/frequency.** F0 varies within a
  speaker (140→228 Hz documented) and overlaps between speakers; x-vector/ECAPA replaced it. The speaker
  *count* is discovered as the number of clusters — no count needed up front.
- **Online diarization is a downgrade and a licensing trap.** Live labels are irrevocable and thrash on
  re-clustering; the only mature open streamer (diart) needs **gated pyannote HF weights**; NeMo Streaming
  Sortformer is **GPU-first and capped at 4 speakers**; Sortformer-v1/DiariZen weights are **CC-BY-NC
  (un-shippable)**. Batch clustering over the finished recording is more accurate, handles unknown count,
  and runs on CPU with ungated ONNX.
- **We already ship the right engine.** `recimport/diarizer.py::SherpaDiarizer` (Apache-2.0 sherpa-onnx,
  ~15 MB ONNX, `num_clusters=-1` auto-count, no torch/GPU/HF-token) diarizes ~45 min in ~30 s on a laptop.
  The proven local pattern (OpenWhispr, ownscribe) is exactly this: transcribe live, diarize the whole file
  at stop.
- **Auto speaker-count is imperfect** (~1 in 4 sessions miscounted, under-count bias) → a human
  merge/rename correction step is mandatory, not optional.

## Decision

Add an opt-in, **hands-free Meeting Mode**: a new long-running daemon state that streams a live transcript
and runs **accurate speaker diarization as a batch post-pass when the meeting stops** (hybrid). It produces
a **saved meeting folder**, never keystroke injection (per ADR-v2-019). OFF by default (`[meeting] enabled=false`).

**Daemon state machine (`core/daemon.py`).** Add `MEETING` to the states (alongside hold-to-talk states,
which are untouched). `meeting_start` enters it: open `AudioRecorder` **without the per-burst cap**, stream
`on_chunk` to (a) a local temp WAV (the authoritative full recording) and (b) a VAD utterance chunker →
faster-whisper → append to a rolling `transcript.jsonl` with word timestamps. Hold-to-talk is disabled while
a meeting runs (mutually exclusive; documented). `meeting_stop` runs the finalize pipeline below and returns
to `IDLE`.

**Finalize (at stop), reusing ADR-v2-125 cores verbatim — do not reimplement:**
1. `SherpaDiarizer.diarize(full_wav)` → turns with auto speaker count (`max_speakers` caps it; `0`=auto).
2. `recimport/align.py::assign_words_to_turns` + `merge_utterances` → per-speaker utterances (pure numpy).
3. `recimport/naming.py` (+ `voiceprint/`): enrolled user → **"You"**, explicit `--names`/`--rename`,
   voiceprint match ≥`min_speaker_seconds`/≥`name_threshold`, else **"Speaker N"**.
4. `recimport/render.py` → `transcript.md` / `.json` / `.srt`; `transcript.json` lossless (word ts +
   per-word speaker).
5. **Opt-in** minutes via [[adr-v2-128-meeting-minutes-generation]] → `notes.md`.

**Output:** `~/.local/share/yazses/meetings/<timestamp>/{transcript.md, transcript.json, notes.md?, audio.wav?}`.

**Unknown-count correction (mandatory).** `yazses meeting relabel <id> --merge s2=s1 --rename s1=Alice`
re-runs only steps 3–5 (pure render), **never re-diarizes** — cheap, honest handling of miscount.

**New module `src/yazses/meeting/` (pure orchestration; heavy tiers lazy, mirrors `recimport/`):**
- `meeting/session.py` — `MeetingSession` lifecycle: start/append-utterance/stop; owns the temp WAV +
  `transcript.jsonl`; pure state, injectable clock/recorder for tests.
- `meeting/segmenter.py` — continuous-audio → utterance chunks via VAD (`vad_calibrated` default; Silero
  VAD optional behind the extra). Pure given a VAD predicate.
- `meeting/finalize.py` — `finalize_meeting(session, config, *, diarizer=None, engine=None, embedder=None,
  profiles=None) -> MeetingResult`. Backends injected; when `diarizer=None`, degrades to an un-attributed
  transcript (still useful). Testable with fakes, zero model downloads.
- `meeting/store.py` — write/read the meeting folder; `list_meetings()`; `relabel(id, merges, renames)`.

**Reuse (do not reimplement):** `audio/recorder.py`, `stt/streaming.py`, `stt/faster_whisper.py::transcribe_words`,
`recimport/{diarizer,align,naming,render}.py`, `voiceprint/*`, `scribe/diarize.py`, `diarize/labels.py`.

**Config — new `[meeting]` `MeetingConfig` (all defaults dormant):** `enabled=False`,
`output_dir=""` (→ `<data>/meetings`), `retain_audio=False`, `live_transcript=True`, `diarize=True`,
`backend="sherpa"`, `max_speakers=0` (0=auto), `min_speakers=0`, `cluster_threshold=0.5`,
`language="en"`, `model=""` (→ `[stt].model`), `vad_backend="calibrated"` (calibrated|silero),
`name_from_voiceprints=True`, `min_speaker_seconds=3.0`, `name_threshold=0.5`, `notes=False`,
`output_format="md"`, `max_minutes=180` (auto-stop safety cap).

**CLI (`cli.py`, panel `_DICTATION`):** `yazses meeting start [--notes] [--no-live]`,
`yazses meeting stop`, `yazses meeting status` (elapsed, live speaker-count estimate, last utterances),
`yazses meeting list`, `yazses meeting relabel <id> [--merge s2=s1]... [--rename s1=Alice]... [--notes]`,
`yazses meeting notes <id>` (generate/regenerate notes for a stored meeting). Daemon IPC methods:
`meeting_start`, `meeting_stop`, `meeting_status`.

**IPC (`ipc/`):** three new JSON-RPC methods above; `status` already exposes `audio_level`/`vad_threshold`
for a live overlay. **Feature registry:** one `meeting` capability row (DEFAULT_OFF); no experimental gate.
**Extra:** reuse the ADR-125 `diarization` extra (sherpa-onnx); Silero VAD optional. **Notes** gated by the
ADR-128 extra.

## Consequences

- Delivers the long-standing meeting-scribe intent (ADR-v2-019) as a real, hands-free path, and unifies the
  live and file diarization stacks — the pure cores are **shared with `yazses transcribe`, not duplicated.**
- **No new heavy dependency**: capture/STT/diarizer/align/naming/render all exist; audio persistence is a
  temp WAV. Base install unchanged.
- On-device, offline (ADR-011): audio is local-only, kept solely for the post-pass and **deleted unless
  `retain_audio`**; embeddings encrypted-corpus-only; naming opt-in/consent-gated, never auto-enrolls others
  (ADR-011/012; embeddings biometric under GDPR Art.9 / BIPA). Not an injection path — a saved artifact.
- Pure `session`/`segmenter`/`finalize`/`store` (injected fakes) unit-test with **zero model downloads**;
  the diarizer factory returns `None` when dormant. CI stays green.
- **Caveats (carried honestly):** auto speaker-count wrong in ~25% of sessions → `relabel` correction is the
  answer; overlapped speech drops the minority speaker (overlap-aware models are gated/GPU, rejected); live
  transcript is best-effort (the batch pass at stop is authoritative) — CPU may lag a large model live;
  word-timestamp drift (100–400 ms) makes turn boundaries approximate on rapid exchanges; first run downloads
  the ~15 MB sherpa models. **Cloud:** none here — deferred to ADR-v2-126.
