# Wave H — SoA research, 10 net-new features

**Date:** 2026 · **Tier:** `design/` — public engineering research · **Author:** Mohsen Seyedkazemi Ardebili
**Companion:** fed [adr-v2-055](../../adr/adr-v2-055-emoji-symbol-voice.md) through
[adr-v2-064](../../adr/adr-v2-064-few-shot-command-spotter.md). See the [waves index](README.md).

> A snapshot of the field, kept as the research record behind the ADRs it fed. Feature status
> should be checked against `yazses features` and the linked ADRs, not this note.

All on-device, off by default, distinct from the ~52 features existing before this wave (v2 +
Waves D/E/F/G). Ranked strongest-first. Anchors web-verified at the time (2025-2026).

1. **Spoken Spreadsheet / Table Mode** — 2D cell-addressed dictation + grid nav ("A1 revenue,
   tab, down, next row"). Anchor: arXiv 0809.3571, Windows Voice Access 2025. Pure:
   `parse_grid_command(text)→KeySequence`. Distinct from Field-Aware (form fields, not 2D cells).
   → [adr-v2-059](../../adr/adr-v2-059-spoken-spreadsheet.md).
2. **Ambient Audio-Event Guard** — auto-pause/alert on doorbell/alarm/name/baby-cry. Anchor:
   SELD wearables (2509.14650), E2PANNs (2506.23437). Pure: label→policy + debounce; PANNs
   deferred. Distinct from Wake-Word (activation, not environmental awareness).
   → [adr-v2-061](../../adr/adr-v2-061-ambient-audio-event-guard.md).
3. **Spoken Temporal Normalizer** — "next Friday at 3" → concrete locale date/time vs the clock.
   Anchor: SCATE (2507.06450), SUTIME/HeidelTime, dateparser. Pure: `resolve_temporal(text,now)`.
   Distinct from Entity ITN (formats number words, doesn't resolve relative dates).
   → [adr-v2-057](../../adr/adr-v2-057-temporal-normalizer.md).
4. **Voice Unit / Currency / Number Conversion** — "twenty miles in km" → "32.19 km", inline,
   offline. Anchor: `pint` registry (an offline Wolfram-Alpha-alternative). Pure: regex grammar
   + factor table. Distinct from ITN (format) + Spoken Math (render) — this *evaluates*.
   → [adr-v2-056](../../adr/adr-v2-056-voice-unit-conversion.md).
5. **On-Device Condense** — a hotkey variant inserts a tightened summary of your own long burst.
   Anchor: Canary-Qwen-2.5B, Omi 0.6B. Pure: extractive TextRank/lead ranking; abstractive LLM
   deferred (reuses `llm_cleanup`). Distinct from Meeting Scribe (others' multi-speaker capture).
   → [adr-v2-062](../../adr/adr-v2-062-on-device-condense.md).
6. **Structured Form / Slot-Filling Dictation** — one utterance → many named template fields.
   Anchor: slot-filling for SpeechLLMs (2510.19326, 2510.15851). Pure: schema + keyword matchers
   → tab-fill; SpeechLLM deferred. Distinct from Field-Aware (formats one field).
   → [adr-v2-063](../../adr/adr-v2-063-slot-filling-dictation.md).
7. **Clipboard-History by Voice** — "paste the second thing I copied". Pure: ring buffer + ordinal
   grammar; embedding recall deferred. Distinct from Smart-Paste (single paste formatting).
   → [adr-v2-060](../../adr/adr-v2-060-clipboard-history-voice.md).
8. **Mid-Utterance Self-Repair** — "email Sarah, no I mean Sara" → "email Sara". Anchor:
   Interactive Dictation / TERTiUS (2307.04008). Pure: editing-term grammar → span-replace before
   injection. Distinct from Spoken Edit (post-injection, separate turn).
   → [adr-v2-058](../../adr/adr-v2-058-mid-utterance-self-repair.md).
9. **Emoji & Symbol by Voice** — "shrug emoji"→🤷, "right arrow"→→, "degree sign"→°. Pure:
   name→codepoint table + phrase replace. Distinct from Voice Punctuation (ASCII only).
   → [adr-v2-055](../../adr/adr-v2-055-emoji-symbol-voice.md).
10. **Few-Shot Personal Command Spotter** — low-latency KWS action triggers from few-shot
    enrollment. Anchor: EdgeSpot (2601.16316), GE2E-KWS (2410.16647). Pure: enroll store +
    cosine dispatch; KWS encoder deferred. Distinct from Wake-Word (single activation phrase).
    → [adr-v2-064](../../adr/adr-v2-064-few-shot-command-spotter.md).

## Ship-now pure (do first)
#1 Spoken Spreadsheet, #3 Temporal Normalizer, #4 Unit Conversion, #9 Emoji & Symbol — fully
dependency-free grammars/lookups extending the existing grammar→dispatch→injector path, each an
accessibility win a cloud tool can't offer privately.

Citations here have not been re-verified against [`research/verify_refs.py`](../verify_refs.py).
