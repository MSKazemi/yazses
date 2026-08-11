# ADR-v2-008 — True Code-Switch Dictation (make `[polyglot]` real)

**Status:** Accepted (2026-07-02) · Wave B
**Context links:** [[adr-v2-000-interaction-layer]], existing `[polyglot]` stub + `polyglot/lid.py`

## Context

The voice-HCI research (internal) shows monolingual
ASR WER spikes 30–50% at code-switch points; end-to-end multilingual models cut boundary
WER up to ~55%, and Google Rambler / Mistral Voxtral now ship mid-sentence code-switching
— but only in cloud/mobile. There is no offline hold-to-talk equivalent. YazSes already
has a `[polyglot]` config stub and `polyglot/lid.py` (language-pair parsing + span LID
scaffolding), currently dormant.

## Decision

Make code-switch dictation real for a user-declared language **pair** (e.g. `fa-en`):
1. Segment the burst and run per-span language ID (`polyglot/lid.py`), constrained to the
   declared pair to bound LID error.
2. Decode each contiguous same-language run with faster-whisper's `language` set
   accordingly (faster-whisper is per-segment), then stitch with existing spacing rules.
3. When the CS-adapted model (`adapter_path`, trained out-of-band) is present, prefer it;
   otherwise fall back to per-span monolingual decode.

Config (existing): `[polyglot] enabled=false`, `pair`, `adapter_path`, `lid`, `mer_gate`.
Wire `lid.py` span routing into the decode path; keep dormant until `pair` is set.

## Consequences

- **+** Natural bilingual dictation, offline — no cloud equivalent exists; reuses the stub.
- **+** Bounded LID error via the declared pair.
- **−** Mid-utterance LID mistakes cause wrong-language garble → restrict to the declared pair,
  expose `mer_gate`; keep off by default.
- **−** Per-span re-decode adds latency → only on the polyglot path (monolingual users unaffected).
