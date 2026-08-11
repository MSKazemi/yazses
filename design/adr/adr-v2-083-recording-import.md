# ADR-v2-083 — Recording Import (batch transcription)

**Status:** Accepted (2026-07-02) · Wave J
**Context links:** [[adr-v2-019-meeting-scribe]] (live vs pre-recorded batch), [[adr-v2-074-diarized-conversation-capture]], [[adr-011]]

## Context

Wave J research (#9) — `yazses transcribe <file>` / drag-drop: transcribe existing voice memos,
lectures, meeting recordings offline at tens-to-hundreds× real-time, emitting `.txt`/`.srt`/`.vtt`
with word timestamps. Your audio archive becomes searchable without the cloud. Distinct from
Ambient Meeting Scribe / Diarized Capture (live) — this is *pre-recorded batch* ingestion, a
different entry point. Anchor: NVIDIA Parakeet-TDT-0.6B-v2 (RTFx≈3386, CC-BY-4.0, 2025-05).

## Decision

Add an opt-in **Recording Import**: `[recimport] enabled=false`. Pure cores:
`merge_word_timestamps(words, max_gap, max_chars)` groups word-level timestamps into caption
segments (split on a silence gap or a length cap), and `write_srt` / `write_vtt` /
`format_timestamp` emit standard subtitle files. Dependency-free and model-agnostic. The Parakeet/
NeMo backend is deferred behind a `parakeet` extra (or reuse faster-whisper as the zero-extra
fallback). OFF by default.

## Consequences

- Batch transcription of an existing archive, offline; the subtitle writers are pure and reusable.
- Distinct from live Meeting Scribe / Diarize (pre-recorded vs live).
- Privacy (ADR-011): local file → local text, explicit per-file.
- Caveat: the STT backend is the deferred heavy tier; the pure segment/subtitle layer is off by
  default.
