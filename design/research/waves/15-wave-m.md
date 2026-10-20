# Wave M — minimal-bandwidth AAC & text-intelligence (SoA research)

**Date:** 2026-07-02 · **Tier:** `design/` — public engineering research · **Author:** Mohsen Seyedkazemi Ardebili
**Companion:** fed [adr-v2-105](../../adr/adr-v2-105-vocal-morse.md) through
[adr-v2-114](../../adr/adr-v2-114-acronym-glossary-manager.md). See the [waves index](README.md).

> A snapshot of the field on the date above, kept as the research record behind the ADRs it fed.
> Feature status should be checked against `yazses features` and the linked ADRs, not this note.

**Method:** background SoA scout (2024-2026 CHI/UIST/ASSETS/TOCHI, Interspeech/ICASSP, arXiv
cs.HC/cs.CL/eess.AS; Apple/MS/Google accessibility) against the full feature-exclusion list at
the time. Every candidate is on-device/offline, off by default, with a pure dependency-light
testable core. All ten evidence anchors were checked at the time.

Deliberately diversified across AAC modalities, data robustness, a new 2-D authoring area,
text-editing intelligence, output formatting, and knowledge capture.

## The ten features (ranked most→least compelling)

1. **Vocal Morse** (`morsevox`) — two distinguishable vocal sounds (short/long) → timed
   Morse pulses → text. The lowest-bandwidth input in the set; even one reliable vocalization
   suffices. Core: `classify_pulse`, `classify_gap`, `MorseDecoder`, `adapt_dot_threshold`.
   Anchor: Google Gboard Morse (2018); adaptive Morse recognition (ScienceDirect).
   → [adr-v2-105](../../adr/adr-v2-105-vocal-morse.md).
2. **Checksum-Validated Data Entry** (`checkdigit`) — dictated account/ID numbers run
   through the field's check-digit algorithm; a Whisper digit slip is caught before it lands.
   Core: `validate(digits, scheme)`, `suggest_fix`. Anchor: Luhn/ISO-7812, IBAN MOD-97/ISO-13616,
   ISBN-10/13, Verhoeff. → [adr-v2-106](../../adr/adr-v2-106-checksum-validated-entry.md).
3. **Diagrams-as-Code by Voice** (`diagramvox`) — "start goes to login; login goes to
   dashboard" → Mermaid/DOT. The first 2-D graph-authoring path in the set. Core:
   `parse_graph_utterance`, `Graph.to_mermaid`/`to_dot`. Anchor: Mermaid; CHI'24 TADA/Umwelt
   accessible-viz authoring. → [adr-v2-107](../../adr/adr-v2-107-diagrams-as-code.md).
4. **Interruptible Read-Back Proofreading** (`proofback`) — barge-in during TTS playback maps
   the timestamp to the exact word and drops the cursor there. Core: `build_schedule`, `word_at`,
   `resolve_target`. Anchor: barge-in dialogue research + dyslexia-TTS proofreading.
   → [adr-v2-108](../../adr/adr-v2-108-interruptible-readback-proofreading.md).
5. **Local Style-Consistency Enforcer** (`styleguard`) — a user/house style sheet applied to
   each dictation (a Vale-lite). Core: `load_stylerules`, `apply_style`. Anchor: Vale, proselint.
   → [adr-v2-109](../../adr/adr-v2-109-style-consistency-enforcer.md).
6. **Screenplay Auto-Format** (`screenplayfmt`) — dialogue dictation → Fountain (scene
   headings, cues, smart quotes). Core: `to_fountain`, `smart_quote_dialogue`. Anchor: Fountain.
   → [adr-v2-110](../../adr/adr-v2-110-screenplay-autoformat.md).
7. **Semantic Line Breaks** (`sembr`) — one clause per source line so git diffs stay clean;
   rendered output unchanged. Core: `semantic_breaks`. Anchor: Semantic Line Breaks Spec;
   ventilated prose. → [adr-v2-111](../../adr/adr-v2-111-semantic-line-breaks.md).
8. **Spoken Spaced-Repetition Capture** (`srscap`) — "remember that X is Y" → an Anki cloze
   card. Core: `detect_fact`, `to_cloze`, `sm2_schedule`. Anchor: Anki/SM-2.
   → [adr-v2-112](../../adr/adr-v2-112-spoken-spaced-repetition.md).
9. **Suggestion-Mode Dictation** (`suggestmode`) — edits emitted as CriticMarkup for later
   review, not applied. Core: `to_criticmarkup`, `diff_to_critic`. Anchor: CriticMarkup spec.
   → [adr-v2-113](../../adr/adr-v2-113-suggestion-mode-dictation.md).
10. **Acronym/Glossary Manager** (`acronyms`) — expand on first use, contract later, warn on
    undefined. Core: `AcronymState.observe`, `resolve`, `audit`. Anchor: technical-style
    first-use convention; LaTeX glossaries/acro. → [adr-v2-114](../../adr/adr-v2-114-acronym-glossary-manager.md).

## Diversity
2 AAC/severe-impairment (#1, #4), 1 data robustness (#2), 1 new interaction area (#3), 3
text-editing intelligence (#5, #9, #10), 2 output formatting (#6, #7), 1 knowledge capture (#8).
Every core is a pure deterministic function/state-machine over already-extracted text or pulse
timings.

Citations here have not been re-verified against [`research/verify_refs.py`](../verify_refs.py).
