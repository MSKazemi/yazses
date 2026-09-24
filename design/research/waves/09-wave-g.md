# Wave G — SoA research, 10 net-new features

**Date:** 2026 · **Tier:** `design/` — public engineering research · **Author:** Mohsen Seyedkazemi Ardebili
**Companion:** fed [adr-v2-045](../../adr/adr-v2-045-entity-itn.md) through
[adr-v2-054](../../adr/adr-v2-054-sign-language-input.md). See the [waves index](README.md).

> A snapshot of the field, kept as the research record behind the ADRs it fed. Feature status
> should be checked against `yazses features` and the linked ADRs, not this note.

All on-device, off by default, distinct from the ~42 features existing before this wave (v2 +
Waves D/E/F). Ranked strongest-first by daily usefulness × distinctness × cleanliness of a
dependency-free core. Anchors verified via web search at the time (2025-2026).

1. **Entity ITN** — inverse text normalization: spoken emails/URLs/paths/versions/dates →
   correctly-written form, no command words. Anchors: NeMo ITN (arXiv 2104.05055), Thutmose
   Tagger (2208.00064), context-aware streaming ITN LM (2505.24229). Pure core: rule-based
   `normalize_entities(text)` (stdlib re). The cleanest core of the ten. → [adr-v2-045](../../adr/adr-v2-045-entity-itn.md).
2. **Field-Aware Dictation** — reshape output by the focused widget's accessibility role
   (number field → digits, search → no trailing period, password → refuse). Anchors: AT-SPI2
   role/state, Windows UIA ControlType/IsPassword, WCAG 1.3.5. Pure: `profile_for_role`. → [adr-v2-047](../../adr/adr-v2-047-field-aware-dictation.md).
3. **Screen-Grounded Dictation** — bias Whisper's `initial_prompt` from on-screen text
   (accessibility tree/clipboard now; OCR VLM deferred). Anchors: GOT-OCR2.0, dots.ocr,
   PaddleOCR-VL-0.9B (2507.05595). Pure: `harvest_screen_terms`. → [adr-v2-051](../../adr/adr-v2-051-screen-grounded-dictation.md).
4. **Redaction Ink** — detect/mask PII+secrets at injection time (card/SSN/key → `[CARD]` or
   hold-and-confirm). Anchors: GLiNER2-PII (2605.09973), gliner-pii-edge. Pure: regex + Luhn. → [adr-v2-046](../../adr/adr-v2-046-redaction-ink.md).
5. **Corpus Voiceprint Scrub** — speaker-anonymize stored learning-corpus audio (DSP now,
   kNN-VC deferred). Anchors: VoicePrivacy 2024 (2404.02677), private kNN-VC (2505.17584). → [adr-v2-048](../../adr/adr-v2-048-corpus-voiceprint-scrub.md).
6. **Compose-in-Target-Language** — speak L1, type L2 (inverse of Wave D's X→English). Anchor:
   SeamlessM4T v2. Pure: `route_translation` pair config + round-trip guard. → [adr-v2-049](../../adr/adr-v2-049-compose-target-language.md).
7. **Silent Lip-Reading Input (VSR)** — webcam lip-reading for aphonia/quiet settings. Anchors:
   Auto-AVSR (2303.14307), VALLR (2503.21408). Pure: `mouth_active` gating. → [adr-v2-053](../../adr/adr-v2-053-silent-lip-reading.md).
8. **Head-Pointer** — continuous cursor by head pose + dwell/blink click. Anchor: MediaPipe Face
   Landmarker blendshapes. Pure: `pose_to_cursor` + `DwellClicker`. → [adr-v2-052](../../adr/adr-v2-052-head-pointer.md).
9. **Grammar Repair (minimal-edit GEC)** for L2 dictation. Anchors: minimal-edit GEC (2506.13148),
   CoEdIT (2305.09857). Pure: `is_minimal_edit` guard + rule pack. → [adr-v2-050](../../adr/adr-v2-050-grammar-repair.md).
10. **Sign-Language Input (SLR)** — webcam ASL→text. Anchor: Google SignGemma (I/O 2025,
    on-device). Pure: `hands_present` + sign-segment boundary detection. → [adr-v2-054](../../adr/adr-v2-054-sign-language-input.md).

## Ship-now pure (do first)
#1 Entity ITN, #2 Field-Aware Dictation, #4 Redaction Ink, #5 Corpus Voiceprint Scrub — the
cleanest dependency-free cores (rule ITN, role→profile map, regex+Luhn PII, DSP scrub). #3 a
close fifth (accessibility/clipboard term-harvest ships; OCR VLM deferred).

Citations here have not been re-verified against [`research/verify_refs.py`](../verify_refs.py).
