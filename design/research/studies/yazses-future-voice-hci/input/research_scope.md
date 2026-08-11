---
id: scope-yazses-future-voice-hci
title: "Futuristic Voice-First HCI Capabilities for YazSes — Research Scope"
type: research_scope
status: draft
scenario: yazses-future-voice-hci
created_at: 2026-05-17
updated_at: 2026-05-17
sources: [src-001, src-002, src-003, src-004, src-005, src-006, src-007, src-008, src-009, src-010, src-011, src-012]
confidence: medium
owner: "Mohsen Seyedkazemi Ardebili"
next_action: "Review Stage 1 gap analysis and approve gap selection before Stage 2"
tags:
  - study
  - status/scope-ready
---

## Topic

**Futuristic voice-first human-computer interaction for offline desktop daemons.**

YazSes is a hold-to-talk voice dictation daemon (Python 3.11+, faster-whisper, CPU/int8, no cloud) that injects transcribed text into any focused application. It currently sits at the commodity end of voice interfaces: speak → transcribe → inject. The next 5–10 years will see voice evolve from a transcription channel into a multimodal, emotionally-aware, context-sensitive, and biosignal-augmented interaction layer spanning coding, ambient computing, XR/metaverse, gaming, and assistive technology. This study maps the research frontier across those domains and derives implementable capabilities that would differentiate YazSes from commodity STT tools while preserving its offline-first, privacy-preserving architecture. The load-bearing premise: the most defensible moat for an offline voice daemon is deep integration with the OS context layer and ambient intent inference — capabilities cloud-dependent tools cannot replicate by design.

## Research Questions

1. **What voice interaction modalities beyond transcription are gaining traction in XR and spatial computing?** [HYPOTHESIS] Gaze+voice and gesture+voice fusion will dominate spatial UX by 2027, and a YazSes mode that reads gaze target from OS accessibility APIs could enable zero-hotkey dictation for spatial contexts.

2. **Can LLM intent routing run fully offline at acceptable latency for real-time command dispatch?** [HYPOTHESIS] Small language models (1–3B parameters, quantised to 4-bit) running on modern consumer CPUs can route voice intents to OS actions in under 200 ms, making cloud-free semantic command dispatch practical today.

3. **What is the current accuracy ceiling for wearable EMG/EEG silent speech recognition, and how close are these to consumer deployment?** [HYPOTHESIS] Sentence-level EMG SSR now exceeds 90% on command vocabularies and approaches consumer readiness, creating a new input modality that YazSes could adopt as a hold-free dictation mode for voice-impaired users.

4. **How are LLM-powered NPCs using voice emotion and intent detection in games, and what primitives do they expose?** [HYPOTHESIS] Real-time emotion inference from speaker audio (valence, arousal) is now achievable at < 50 ms latency and could be offered as a YazSes "gaming mode" that annotates injected text with emotion metadata for NPC APIs.

5. **What does the research say about always-on, proactive ambient voice interfaces — and what privacy mechanisms make them acceptable?** [HYPOTHESIS] Hybrid local-wake/cloud-process architectures are giving way to fully local always-on inference; a YazSes "ambient mode" that runs a keyword spotter in the background and activates the full STT pipeline contextually is both technically viable and privacy-preserving.

6. **Which multimodal fusion architectures (voice + gaze/gesture/touch) produce the best command-disambiguation accuracy for coding and creative workflows?** [HYPOTHESIS] Early fusion of voice with screen-region context (what is visible/focused in the IDE) outperforms late fusion because it reduces ASR n-best re-ranking error when technical vocabulary is involved.

7. **What are the most critical unmet AAC needs that an offline voice daemon could address, and what AI techniques are being validated?** [HYPOTHESIS] Personalised voice synthesis for individuals with dysarthria and AI-driven communicative-movement interpretation are the two highest-impact gaps; both can be integrated into YazSes as an accessibility back-end without cloud dependency.

## Inclusion / Exclusion Criteria

**Inclusion criteria** — a source must satisfy ALL of:

- Addresses voice interaction, multimodal HCI, speech recognition, biosignal input, or AI-driven NPC/ambient systems
- Has a public URL, peer-reviewed venue, or maintained arXiv preprint
- Published or updated 2024-01-01 or later (for fast-moving domains)
- Access type open or restricted (no paywalled-only sources)

**Exclusion criteria** — a source is excluded if ANY of:

- Purely cloud-dependent architecture with no offline applicability
- Vendor marketing material with no technical substance or evaluation data
- Duplicate of another source with no additional contribution
- Addresses only ASR accuracy on clean speech benchmarks without broader HCI context

## Source Taxonomy

| Source type | Count | Rationale |
|-------------|-------|-----------|
| paper (arXiv preprint) | 8 | Primary research on algorithms and systems |
| paper (peer-reviewed) | 4 | ACM, Springer, PMC for methodological rigour |
| **Total** | **12** | Covers all 8 research dimensions |

## Search Plan

Sources were found via targeted web searches across 8 domains in May 2026, using Google Search with domain constraints. Seed queries included: "voice coding assistants LLM 2025", "multimodal voice gaze gesture HCI arxiv 2025", "silent speech EMG wearable 2025", "LLM NPC voice gaming 2025", "ambient voice computing 2025", "AAC motor impairment AI 2025", "biosignal speech augmentation EEG EMG 2025", "VoiceBench LLM voice benchmark". arXiv IDs were resolved to confirm real existence; DOIs verified where available. No sources were invented.

**Seed queries / keywords:**
- "multimodal natural interaction XR spatial computing 2025"
- "VoiceBench LLM voice assistants benchmark"
- "edge cloud adaptive inference speech-to-action offline"
- "silent speech EMG wearable keyboard-free 2025"
- "LLM NPC voice emotion gaming 2025"
- "AAC communicative movements AI disability 2025"
- "ambient voice proactive always-on 2025"
- "multimodal fusion speech gaze gesture ICMI 2025"

## Target Users

1. **Knowledge workers and developers** — spend 6+ hours/day in IDEs and terminals. Currently use voice only for occasional dictation; frustrated that voice tools don't understand code context, project structure, or intent beyond literal transcription. Want voice to drive the IDE the way a keyboard-shortcut power user does, without leaving the flow state. [HYPOTHESIS]

2. **Gamers and XR creators** — play immersive titles and build spatial environments where keyboard/mouse breaks presence. Want voice to feel like talking to a character or a world, not issuing commands to a machine. Expect emotional awareness and contextual memory from voice NPCs. [HYPOTHESIS]

3. **Users with motor or speech disabilities** — cannot rely on keyboard, mouse, or fluent speech. Need voice interfaces that work with dysarthric speech, silent EMG input, or communicative body movements. Currently underserved by mainstream STT that requires clear pronunciation and deliberate activation. [HYPOTHESIS]

## Scope Boundaries

**IN SCOPE:**
- Voice interaction modalities beyond transcription (emotion, intent, context, biosignal)
- Offline and edge-deployable architectures for voice+LLM pipelines
- Multimodal fusion: voice + gaze, gesture, screen context, biosignal
- Gaming and XR voice interaction patterns
- Assistive technology: AAC, silent speech, dysarthric speech, motor-impaired input
- Ambient and proactive voice interfaces that preserve privacy
- LLM-based semantic command dispatch (local, small models)

**OUT OF SCOPE (explicitly):**
- Cloud-only voice APIs (Alexa, Google Assistant) — no offline applicability for YazSes
- Full brain-computer interface implants (invasive ECoG) — consumer timeline > 10 years
- General speech recognition accuracy benchmarks without HCI context
- Multilingual STT model training — outside YazSes roadmap scope

## Output Goal

A successful Stage 1 produces:

- **12 ResearchCards** (one per source) with every claim tagged `[EVIDENCE src-NNN]`, `[HYPOTHESIS]`, or `[TODO: find source]`
- **One SoA Matrix** comparing sources across 9 dimensions specific to voice-first HCI (not default MLOps dimensions)
- **One Gap Analysis** identifying ≥8 gaps with ≥2 critical-severity gaps, each supported by evidence from the matrix and an opportunity statement linked to one of the 3 personas above

**Human review gate (after Stage 1, before Stage 2):** A reader unfamiliar with YazSes should be able to read the gap analysis and identify 3–5 capability directions that would make YazSes genuinely differentiated from commodity STT tools over a 3–5 year horizon.

---

**Key outputs:** *(fill in as stages complete)*
