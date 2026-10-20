# Wave N — structural editing, i18n & accessibility-output correctness (SoA research)

**Date:** 2026-07-02 · **Tier:** `design/` — public engineering research · **Author:** Mohsen Seyedkazemi Ardebili
**Companion:** fed [adr-v2-115](../../adr/adr-v2-115-hatselect.md) through
[adr-v2-124](../../adr/adr-v2-124-outline.md). See the [waves index](README.md).

> A snapshot of the field on the date above, kept as the research record behind the ADRs it fed.
> Feature status should be checked against `yazses features` and the linked ADRs, not this note.

**Method:** background SoA scout (2024-2026 CHI/UIST/ASSETS, Interspeech/ICASSP, arXiv
cs.HC/cs.CL/eess.AS; Cursorless; ITRANS/Pinyin; liblouis; Unicode UTS-39) against the full
feature-exclusion list at the time. Every candidate is on-device/offline, off by default, with a
pure dependency-light testable core. All ten anchors were checked at the time.

Diversified across code/terminal structural editing, internationalization (transliteration,
diacritics, Braille), accessibility modalities (anomia, eyes-free, blind/screen-reader, cognitive
load), security/correctness, and output structuring.

## The ten features (ranked most→least compelling)

1. **HatSelect** (`hatselect`) — every visible token gets a spoken label; "select alpha to
   charlie", "delete bravo" edit *structurally* without cursor motions. Core: `assign_labels`,
   `resolve_reference`, `plan_structural_edit`. Anchor: Cursorless (Talon) hats — the SoA for
   hands-free structured code editing. → [adr-v2-115](../../adr/adr-v2-115-hatselect.md).
2. **Transliteration** (`translit`) — dictate a native language in Latin letters ("salam,
   chetori?") → native script. Whisper mis-transcribes low-resource native audio but nails
   romanized phonetics. Core: `transliterate`, `detect_scheme`. Anchor: ITRANS, Pinyin, Google
   Input Tools. → [adr-v2-116](../../adr/adr-v2-116-transliteration.md).
3. **BrailleOut** (`brailleout`) — emit Grade-2 Unicode Braille / `.brf` so a Braille-display
   or DeafBlind user gets dictation directly in Braille. Core: `to_braille`. Anchor: liblouis,
   UEB. → [adr-v2-117](../../adr/adr-v2-117-brailleout.md).
4. **WordFind** (`wordfind`) — an offline reverse-dictionary: "the word for when water turns to
   gas" → a ranked shortlist. Core: `rank_candidates`. Anchor: WordNet reverse-dictionary; TREC
   2025 Tip-of-the-Tongue; anomia/AAC research. → [adr-v2-118](../../adr/adr-v2-118-wordfind.md).
5. **Echo** (`echo`) — "play that back" replays your *own captured audio* for a text span
   (not TTS), catching homophone/ASR errors eyes-free. Core: `build_span_index`,
   `resolve_playback_target`. Anchor: Vertanen eyes-free ASR-error detection (arXiv 2410.20564).
   → [adr-v2-119](../../adr/adr-v2-119-echo.md).
6. **SRPace** (`srpace`) — pace injection to a screen reader's reading rate, clause-chunked,
   instead of a burst. Core: `plan_injection_schedule`. Anchor: screen-reader comprehensibility
   research. → [adr-v2-120](../../adr/adr-v2-120-srpace.md).
7. **LoadGuard** (`loadguard`) — rising cognitive-load speech signals widen confirmations and
   defer risky actions. Core: `estimate_load`, `guard_policy`. Anchor: cognitive-load-from-speech
   (arXiv 2606.12971); ADHD accessibility research. → [adr-v2-121](../../adr/adr-v2-121-loadguard.md).
8. **Diacritize** (`diacritize`) — restore diacritics on dictated words ("cafe"→"café",
   "naive"→"naïve"). Core: `restore_diacritics`. Anchor: NAACL 2024 diacritics restoration.
   → [adr-v2-122](../../adr/adr-v2-122-diacritize.md).
9. **SafeGlyph** (`safeglyph`) — flag homoglyph/confusable hazards in dictated identifiers/
   URLs/secrets (Cyrillic "а" vs Latin "a"). Core: `scan_confusables`, `normalize_ascii`.
   Anchor: Unicode UTS-39. → [adr-v2-123](../../adr/adr-v2-123-safeglyph.md).
10. **Outline** (`outline`) — "new item / indent / promote / collapse" drives a live outline
    tree → Markdown/OPML. Core: `apply_outline_op`, `render`. Anchor: OPML/outliner verbs; ADHD
    idea-capture accessibility research. → [adr-v2-124](../../adr/adr-v2-124-outline.md).

## Diversity
Code/terminal (1), i18n (2, 8, +3 scripts), accessibility modalities (3 Braille, 4 anomia, 5/6
eyes-free & blind, 7 cognitive), security/correctness (9), output structuring (10). Every core is
a pure deterministic function/state-machine; heavy backends (liblouis, embedding rerankers, CNN
diacritizers) are optional lazy extras.

Citations here have not been re-verified against [`research/verify_refs.py`](../verify_refs.py).
