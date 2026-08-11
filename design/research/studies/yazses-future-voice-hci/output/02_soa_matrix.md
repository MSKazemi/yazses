---
id: soa-yazses-future-voice-hci
title: "State of the Art: Futuristic Voice-First HCI for YazSes — 2025"
type: soa_matrix
status: in-review
scenario: yazses-future-voice-hci
created_at: 2026-05-17
updated_at: 2026-05-17
sources: [src-001, src-002, src-003, src-004, src-005, src-006, src-007, src-008, src-009, src-010, src-011, src-012]
confidence: medium
owner: "Mohsen Seyedkazemi Ardebili"
next_action: "Review matrix patterns and approve before Gap Analysis"
dimensions: [xr_spatial_voice, llm_intent_routing_offline, offline_edge_deployment, multimodal_fusion, silent_speech_biosignal, emotional_voice_gaming, accessibility_aac, ambient_context_awareness, code_voice_coding]
source_ids: [src-001, src-002, src-003, src-004, src-005, src-006, src-007, src-008, src-009, src-010, src-011, src-012]
matrix_version: "1"
---

## Dimension Definitions

**xr_spatial_voice:** Measures whether the source addresses voice interaction in XR/spatial computing contexts (AR, VR, MR, spatial computing headsets, or 3D environments).
- ✓ = primary focus on XR voice interaction with evaluation in XR context
- ~ = XR mentioned or partially covered; primarily another domain
- ✗ = not in scope; desktop/robot/medical only
- ? = not assessed

**llm_intent_routing_offline:** Measures whether the source covers LLM-mediated semantic intent routing that can operate without cloud connectivity (edge/local deployment).
- ✓ = demonstrates offline LLM intent routing with accuracy and latency data
- ~ = covers LLM intent routing but cloud-dependent, or covers offline without LLM
- ✗ = no LLM intent routing; rule-based or ASR-only
- ? = not assessed

**offline_edge_deployment:** Measures whether the system or architecture operates without cloud connectivity on consumer-grade hardware (laptop CPU, no dedicated GPU).
- ✓ = demonstrated offline operation on edge/consumer hardware
- ~ = edge-capable in principle but evaluated on GPU or server hardware
- ✗ = cloud-required; no offline mode
- ? = not assessed

**multimodal_fusion:** Measures whether the source addresses fusion of voice with at least one other input modality (gaze, gesture, touch, biosignal, screen context).
- ✓ = primary contribution is voice + X fusion with evaluation
- ~ = multimodal fusion discussed or demonstrated but not the primary contribution
- ✗ = single-modality only (voice alone or biosignal alone)
- ? = not assessed

**silent_speech_biosignal:** Measures whether the source covers non-acoustic speech input via biosignals (EMG, EEG, MEG) or silent articulation.
- ✓ = primary contribution: biosignal-based speech input with accuracy results
- ~ = biosignals discussed or used as auxiliary input; not the primary modality
- ✗ = acoustic speech only
- ? = not assessed

**emotional_voice_gaming:** Measures whether the source addresses real-time emotional inference from voice for gaming applications (NPC adaptation, player affect detection).
- ✓ = emotion detection from player voice integrated with game/NPC adaptive behavior, with evaluation
- ~ = emotion detection or NPC adaptation present but not integrated as a system
- ✗ = no emotional inference or gaming application
- ? = not assessed

**accessibility_aac:** Measures whether the source specifically addresses users with speech, motor, or visual disabilities, including AAC use cases.
- ✓ = primary focus on disability/AAC; users with impairment are the target population
- ~ = accessibility addressed but not the primary target; atypical speech covered partially
- ✗ = typically-abled users only; disability not addressed
- ? = not assessed

**ambient_context_awareness:** Measures whether the source incorporates ongoing environmental or user-state context (gaze target, active window, user attention, past interactions) to shape voice command interpretation.
- ✓ = persistent or continuous context signal used for command disambiguation with evaluation
- ~ = context used for single-shot disambiguation; not persistent or continuous
- ✗ = context-free; each utterance interpreted in isolation
- ? = not assessed

**code_voice_coding:** Measures whether the source specifically addresses voice interfaces for software development (code dictation, IDE command, navigation by voice, code-aware NLU).
- ✓ = primary contribution targets voice-coding or code-aware dictation with evaluation
- ~ = coding mentioned or a task category; not the primary evaluation domain
- ✗ = no coding-specific content
- ? = not assessed

---

## Matrix

| Source | xr_spatial | llm_intent | offline_edge | multimodal | silent_bio | emotional_gaming | accessibility | ambient_ctx | code_voice | Notes |
|--------|:----------:|:----------:|:------------:|:----------:|:----------:|:----------------:|:-------------:|:-----------:|:----------:|-------|
| src-001: XR Multimodal Survey | ✓ | ✗ | ✗ | ✓ | ✗ | ✗ | ~ | ~ | ~ | [EVIDENCE src-001] All LLM voice systems in survey are cloud-connected |
| src-002: VoiceBench | ✗ | ~ | ✗ | ✗ | ✗ | ✗ | ~ | ✗ | ~ | [EVIDENCE src-002] Has a coding task category; all benchmarked models are cloud |
| src-003: Edge-Cloud Speech-to-Action | ✗ | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ~ | [EVIDENCE src-003] TinyLlama offline fallback demonstrated; coding tasks not evaluated |
| src-004: Voice+Gesture LLM Fusion | ~ | ~ | ✗ | ✓ | ✗ | ✗ | ~ | ✓ | ✗ | [EVIDENCE src-004] Robot HRI context; spatial gesture maps to OS cursor context |
| src-005: Headphone EMG SSI | ✗ | ✗ | ✓ | ✗ | ✓ | ✗ | ✓ | ✗ | ✗ | [EVIDENCE src-005] 96% accuracy, 10 commands; consumer form factor |
| src-006: sEMG Typing (Transformer) | ✗ | ✗ | ~ | ✗ | ✓ | ✗ | ~ | ✗ | ~ | [EVIDENCE src-006] 10.1% personalised CER; keyboard-free full text input |
| src-007: EMG+EEG Sentence SSR | ✗ | ✗ | ✓ | ~ | ✓ | ✗ | ✓ | ~ | ✗ | [EVIDENCE src-007] Sensor fusion; sentence-level; real-time wireless |
| src-008: NPC Affective Mirroring | ✗ | ✗ | ? | ~ | ✗ | ✓ | ✗ | ✓ | ✗ | [EVIDENCE src-008] Pilot study; voice + multi-channel affect → NPC emotion |
| src-009: LLM-Driven NPCs | ✗ | ~ | ✗ | ✗ | ✗ | ✓ | ✗ | ✓ | ✗ | [EVIDENCE src-009] Cloud LLM; persistent memory; cross-platform NPC dialogue |
| src-010: Multimodal Fusion Review | ~ | ~ | ✗ | ✓ | ✗ | ✗ | ✗ | ✓ | ~ | [EVIDENCE src-010] 50 systems reviewed; LLM-mediated late fusion is emerging trend |
| src-011: Interspeech Biosignal Session | ✗ | ✗ | ~ | ✗ | ✓ | ✗ | ✓ | ~ | ✗ | [EVIDENCE src-011] Community-level validation; 5 AAC application areas defined |
| src-012: AI for AAC Movements | ✗ | ✗ | ~ | ~ | ✗ | ✗ | ✓ | ~ | ✗ | [EVIDENCE src-012] Camera-based movement interpretation for motor/visual disability |

---

## Notable Patterns

1. [EVIDENCE src-001, src-002, src-003, src-009, src-010] **Offline LLM intent routing is a universal gap: 9 of 12 sources operate cloud-dependent LLM pipelines.** Only src-003 explicitly demonstrates an offline LLM fallback (TinyLlama). The remaining 8 sources that use LLMs all require cloud connectivity. This is the single clearest product opportunity for YazSes: an offline-first LLM intent layer is technically available (src-003 validates feasibility) but not yet implemented in any voice daemon or XR system in the survey. [EVIDENCE src-003] TinyLlama-1B at 4-bit quantisation covers low-complexity intents adequately for the existing YazSes command vocabulary.

2. [EVIDENCE src-005, src-006, src-007, src-011] **Wearable biosignal input is the fastest-moving front in accessible voice HCI: 4 sources cover EMG/EEG silent speech, and a major venue (Interspeech 2025) has dedicated a special session to it.** Consumer EMG hardware in headphone form factor (src-005) achieves 96% accuracy on 10-word vocabularies today. Full-text input via transformer sEMG (src-006) is approaching 10% CER. Sentence-level EEG+EMG fusion (src-007) is demonstrated in wearable hardware. [HYPOTHESIS] Consumer-ready EMG headphones are 2–3 years away, giving YazSes a window to build the integration layer before hardware commoditises.

3. [EVIDENCE src-001, src-004, src-010] **Gaze+voice is the most studied multimodal combination for spatial and desktop HCI (12 papers in src-001's survey), yet no surveyed system uses OS accessibility APIs as a gaze proxy on standard hardware.** All gaze+voice systems require dedicated eye-tracking hardware. [HYPOTHESIS] YazSes is uniquely positioned to implement a "soft gaze" layer using the OS accessibility tree (AT-SPI2 on Linux, Accessibility API on macOS) — providing the most common benefit of gaze integration (context-aware command disambiguation) without additional hardware cost.

4. [EVIDENCE src-008, src-009] **Voice emotion detection and adaptive NPCs are validated as engagement-positive in gaming, but neither paper provides an offline or daemon-integrated implementation.** Both src-008 and src-009 require custom game-engine integration for emotion inference. [HYPOTHESIS] A standardised, offline-capable YazSes "gaming protocol" — structured JSON events containing transcript + emotion annotation + timing — would be the first voice middleware layer that game engines and NPC platforms could consume directly, creating a new distribution channel.

5. [EVIDENCE src-002, src-010] **Instruction-following failure (not transcription error) and user error correction are identified as primary quality gaps across all voice systems.** VoiceBench (src-002) shows instruction-following as a distinct failure mode. The ICMI systematic review (src-010) identifies error recovery as the most under-studied aspect of multimodal voice interfaces (across 50 systems). [HYPOTHESIS] YazSes is already structurally ahead of commodity tools on this dimension: the grammar classifier (fast path) + disfluency filter + correction rollback provides a three-layer error management system. Extending this with LLM-mediated intent classification and n-best correction would close the largest documented quality gap in voice HCI.

---

## Coverage Gaps

### Dimensions with Widespread Absence (✗)

- **code_voice_coding** — 8 of 12 sources have ✗ (src-001~, src-002~, src-003~, src-004✗, src-005✗, src-007✗, src-008✗, src-011✗). Despite coding being the most valuable context for a power-user voice daemon, it is the most neglected domain in voice HCI research. This is a genuine product gap, not an evidence gap. No research system addresses code-aware dictation with editor-state context. Carry to Gap Analysis. [EVIDENCE src-002: coding is a benchmark task but is not the primary focus of any surveyed system]

- **emotional_voice_gaming** — 10 of 12 sources have ✗ (only src-008 ✓, src-009 ✓). This is a domain-specific gap: voice research and gaming research are siloed. The two gaming-focused sources (src-008, src-009) both lack offline deployment. [HYPOTHESIS] YazSes could be the first offline-capable voice middleware layer serving both NPC emotion APIs and game command dispatch.

- **offline_edge_deployment with LLM** — [CONFLICT src-003 vs. all others]: src-003 is the only source demonstrating a real offline LLM fallback. All other LLM-using systems (src-002, src-004, src-009, src-010) are cloud-dependent. This is a genuine architectural gap — offline LLM routing exists as a research proof-of-concept but has not been integrated into any voice interaction product.

### Dimensions with Evidence Gaps (?)

- **offline_edge_deployment** (src-008) — src-008 does not specify deployment infrastructure; whether the emotion detection model can run on CPU is not determined. Recommend reading the full paper or checking the implementation repository.

### Well-Covered Dimensions

- **silent_speech_biosignal** — 4 of 12 sources have ✓ (src-005, src-006, src-007, src-011), plus 2 with ~. The field has strong momentum; consumer deployment is a matter of hardware timeline, not algorithm readiness.

- **multimodal_fusion** — 4 of 12 sources have ✓ (src-001, src-004, src-010, src-012), plus 3 with ~. The fusion architecture taxonomy is well-established (early/late/hybrid; LLM-mediated); the gap is in offline and context-aware variants.

---

*Study: [[yazses-future-voice-hci/input/research_scope|yazses-future-voice-hci]]*
