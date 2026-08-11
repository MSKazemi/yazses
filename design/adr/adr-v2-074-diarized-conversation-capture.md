# ADR-v2-074 — Diarized Conversation Capture with Rename-by-Voice

**Status:** Accepted (2026-07-02) · Wave I
**Context links:** [[adr-v2-019-meeting-scribe]] (bulk transcript vs renameable turns), [[adr-v2-027-multi-user-voiceprint]] (identity/auth), [[adr-012-self-improvement-loop]], [[adr-011]]

## Context

Wave I research (#2) — dictate a live two-or-more-person conversation as attributed, labeled text:
segment into speaker turns, inject attributed Markdown (`**Alice:** …`), and rename labels by
voice ("call speaker two Alice") with the mapping persisting for the session. A Deaf/HoH awareness
win too. Anchor: `pyannote/speaker-diarization-community-1` + pyannote.audio 4.0 (2025), the best
open on-device diarizer. Distinct from Ambient Meeting Scribe (bulk transcription) and Multi-User
Voiceprint Profiles (identity/auth) — neither gives renameable, per-turn attribution.

## Decision

Add an opt-in **Diarized Conversation Capture**: `[diarize] enabled=false`. Pure cores:
`SpeakerLabelMap` (canonicalizes raw ids like `SPEAKER_00` / "speaker two" → `speaker_2`, holds
display names, renders a default pretty label), `parse_rename(text)` (understands "call/rename/
name speaker N …" and "speaker N is …"), and `render_attributed_markdown(turns, label_map)` (one
`**Name:** text` line per turn, merging consecutive same-speaker turns). Dependency-free. The
pyannote diarization model is deferred behind a `diarize` extra; embeddings reuse the encrypted
corpus (ADR-012). OFF by default.

## Consequences

- Renameable per-turn attribution — beyond bulk Meeting Scribe.
- Pure label map + rename grammar + renderer → fully testable with a turn list.
- Privacy (ADR-011/012): audio + embeddings stay local, encrypted-corpus only.
- Caveat: the diarizer is the deferred heavy tier; the pure layer is off by default.
