---
id: gap-yazses-future-voice-hci
title: "Gap Analysis: Futuristic Voice-First HCI for YazSes — 2025"
type: gap_analysis
status: in-review
scenario: yazses-future-voice-hci
created_at: 2026-05-17
updated_at: 2026-05-17
sources: [src-001, src-002, src-003, src-004, src-005, src-006, src-007, src-008, src-009, src-010, src-011, src-012]
confidence: medium
owner: "Mohsen Seyedkazemi Ardebili"
next_action: "HUMAN REVIEW REQUIRED — approve gap selection and priority order before Stage 2 (CapabilityCards)"
gap_count: 9
critical_gap_count: 3
source_ids: [src-001, src-002, src-003, src-004, src-005, src-006, src-007, src-008, src-009, src-010, src-011, src-012]
soa_matrix_id: soa-yazses-future-voice-hci
---

## Gap Registry

| gap_id  | title | description | evidence | severity | opportunity |
|---------|-------|-------------|----------|----------|-------------|
| gap-001 | Offline LLM intent routing absent in all voice daemons | No voice daemon or XR system in the survey combines offline-first architecture with LLM-mediated semantic intent routing. The field either uses cloud LLMs (quality) or rule-based offline systems (YazSes today). The combination does not exist as a deployed product. | [EVIDENCE src-003] TinyLlama offline fallback; [EVIDENCE src-001, src-002, src-009, src-010] cloud LLM dependency in all other systems | critical | YazSes adds a local SLM intent layer (1–3B parameter quantised model) on top of the existing grammar classifier, providing semantic command coverage beyond the 25 regex rules while remaining offline and privacy-preserving. |
| gap-002 | Code-aware voice dictation is unsolved everywhere | Despite coding being the highest-value context for power-user voice tools, no surveyed system addresses code-specific dictation with editor-state context (active file, language, cursor line, symbol under cursor). VoiceBench includes a coding category but no system targets it as a primary use case. | [EVIDENCE src-002] coding task in VoiceBench; [EVIDENCE src-001] XR "typing" task grows but no code-specific solution | critical | YazSes integrates with LSP (Language Server Protocol) to inject file-type, cursor context, and active symbol into the transcription prompt — making it the first voice tool that understands where in the code the user is dictating. |
| gap-003 | No voice daemon integration for EMG silent input | EMG-based silent speech is technically ready (96% accuracy at 10 commands, src-005; 10% CER for full text, src-006) but no desktop voice daemon provides an EMG input backend. Integration into a real workflow requires building this bridge. | [EVIDENCE src-005, src-006, src-007, src-011] EMG/EEG accuracy demonstrated; [HYPOTHESIS] no desktop integration exists | critical | YazSes implements an EMG backend implementing the existing HotkeyBackend protocol, making EMG a first-class input modality for open-office silent use, accessibility, and future wearable computing contexts. |
| gap-004 | Gaze+voice without eye-tracking hardware | All gaze+voice research requires dedicated eye-tracking hardware. No system uses OS accessibility APIs as a gaze proxy (active window, focus element, cursor position) to provide the same disambiguation benefit on standard hardware. | [EVIDENCE src-001, src-004, src-010] gaze+voice research requires hardware; [HYPOTHESIS] OS APIs provide equivalent context signal | major | YazSes implements a context injection layer that reads the OS accessibility tree (AT-SPI2/macOS Accessibility) and prepends active-window context to the LLM intent prompt, replicating gaze disambiguation without additional hardware. |
| gap-005 | Gaming voice protocol: no offline middleware layer | Voice emotion detection for gaming (src-008, src-009) is validated as engagement-positive but both systems require custom per-game audio processing. No standardised, offline, game-engine-agnostic voice middleware exists that provides both command dispatch and emotion annotation. | [EVIDENCE src-008, src-009] NPC emotion from voice validated; [HYPOTHESIS] no standardised middleware layer exists | major | YazSes defines a "gaming protocol" — a structured JSON event stream (transcript + emotion annotation + confidence + timing) that any game engine consuming it via IPC gets both voice commands and emotion metadata from a single offline daemon. |
| gap-006 | AAC users have no offline desktop voice daemon | Existing AAC devices (Tobii Dynavox, Grid 3) are proprietary and separate from the desktop OS. Users with motor/speech disabilities who use a standard computer have no open-source, offline voice daemon that integrates movement, gaze, or silent EMG input with desktop text injection. | [EVIDENCE src-011, src-012] AAC research active; [EVIDENCE src-005, src-007] biosignal input validated; [HYPOTHESIS] no desktop integration | major | YazSes implements an "AAC mode" that accepts multiple input backends (acoustic voice, EMG, camera-based gesture/gaze via MediaPipe) through a common protocol, routing all inputs to the same text injection and intent dispatch pipeline. |
| gap-007 | Dysarthric and atypical speech unsupported | All benchmarked voice systems (src-002) show significant degradation on non-standard speech. No voice daemon provides a personalised acoustic model or speaker-adaptation layer that improves accuracy for users with dysarthria, Parkinson's tremor, or strong accents. | [EVIDENCE src-002] performance degrades on accented/disfluent speech; [EVIDENCE src-011] speech restoration is Interspeech 2025 focus | major | YazSes enrollment wizard (already present) is extended to collect speech samples for lightweight speaker adaptation (LoRA fine-tuning of the faster-whisper model) — yielding a personalised acoustic model that runs offline and dramatically reduces WER for atypical speakers. |
| gap-008 | Ambient/proactive voice mode does not exist offline | Proactive, always-listening voice interfaces that activate contextually (not on hotkey) exist only as cloud-connected products (Siri, Google Assistant). No offline voice daemon provides an ambient mode with a local keyword spotter front-end and privacy-preserving activation. | [HYPOTHESIS] cloud-only always-on voice; [EVIDENCE src-001] speech-only interaction growing in XR ambient contexts | major | YazSes ambient mode: a local, CPU-efficient wake-word detector (openWakeWord or equivalent) runs continuously in a background thread; when confidence exceeds a threshold, it hands off to the full faster-whisper pipeline — no cloud, no hotkey required. |
| gap-009 | No user error correction protocol in voice interfaces | Error recovery from misinterpreted voice commands is the most under-studied aspect of voice HCI across 50 reviewed systems (src-010). No voice daemon exposes an n-best correction interface or a structured voice undo protocol. | [EVIDENCE src-010] error recovery gap across 50 systems; [EVIDENCE src-002] instruction-following failure is distinct mode | minor | YazSes voice undo protocol: the daemon retains the n-best intent list from each command classification; the user can say "that was wrong" to select the next-best interpretation without re-speaking the original command. |

---

## Critical Gaps (Detailed)

### gap-001: Offline LLM Intent Routing Absent in All Voice Daemons

**Problem Statement**

[EVIDENCE src-001, src-002, src-009, src-010] Every voice system in this survey that uses LLMs for semantic intent resolution is cloud-dependent. The entire research community has converged on cloud LLMs as the quality solution and offline rule-based systems as the privacy solution — but no system combines both. [EVIDENCE src-003] The technical proof-of-concept exists: TinyLlama-1.1B at 4-bit quantisation demonstrates acceptable accuracy on low-complexity speech-to-action intents on edge hardware. The gap is not algorithmic; it is a deployment and integration gap — no voice daemon has built the offline LLM routing layer.

**Confirming Sources**

- [EVIDENCE src-002] VoiceBench: all benchmarked models (GPT-4o, Gemini, open-source) are cloud-deployed; no offline LLM system is included in the benchmark. Instruction-following failure is a primary quality gap even for cloud models.
- [EVIDENCE src-003] Adaptive edge-cloud inference paper: explicitly names the cloud/offline tradeoff; TinyLlama is the only offline LLM demonstrated for speech-to-action. Accuracy on low-complexity intents is adequate; complex multi-step instructions show quality degradation.
- [EVIDENCE src-001] XR survey: all LLM-mediated voice systems in XR context are cloud-connected; "offline XR voice with LLM" is an open research problem.
- [EVIDENCE src-009] LLM NPCs: cloud LLM dependency for NPC dialogue is universal; offline NPC dialogue is listed as future work.

**Why Critical (Not Just Major)**

[HYPOTHESIS] Without this capability, YazSes cannot close the quality gap with cloud-dependent voice tools for users who value privacy or work offline. The current 25-rule grammar classifier covers ~80% of common commands but fails on natural phrasing variation ("close this tab", "shut the browser", "dismiss this window" all mean the same thing). An LLM intent layer would bring coverage to >95% of natural phrasing variants. [HYPOTHESIS] As voice interaction becomes the primary interface in XR and ambient computing, the quality gap between rule-based and LLM-mediated systems will become the primary user-visible failure mode — making this gap blocking for the v0.4+ roadmap.

**Opportunity Scope**

[HYPOTHESIS] YazSes implements a three-tier routing stack: (1) grammar regex fast path — sub-10 ms, handles known intents; (2) local SLM (Phi-3-mini or TinyLlama-1.1B at 4-bit) — 100–300 ms, handles natural phrasing variants of known intents; (3) optional cloud API ceiling — user-controlled, for complex multi-step tasks. The existing CommandIntent dataclass and dispatch.py become the output target for all three tiers. This positions YazSes as the only offline voice daemon with LLM-quality intent resolution — a uniquely defensible position because cloud tools cannot match the privacy guarantee and privacy tools cannot match the quality.

---

### gap-002: Code-Aware Voice Dictation Is Unsolved Everywhere

**Problem Statement**

[EVIDENCE src-002] VoiceBench includes a coding task category, but no surveyed system provides voice dictation that is aware of the current code context: what language is being written, what function or class is in scope, what variable names have been declared. [EVIDENCE src-001] XR systems treat voice-for-typing as a generic text entry problem — code-specific challenges (camelCase, identifiers, symbols, boilerplate) are not addressed in any paper. The result is that every developer who tries voice coding today must mentally translate their intent into ASR-friendly language and then correct transcription errors in code syntax.

**Confirming Sources**

- [EVIDENCE src-002] VoiceBench: coding is a benchmark task, but no evaluated model achieves notably higher quality on coding vs. other tasks; no system provides code-context injection to improve accuracy.
- [EVIDENCE src-001] XR "typing" tasks grew significantly in 2024 research, but code-specific evaluation is absent from all reviewed systems.
- [HYPOTHESIS] Language server protocol (LSP) is available in all major IDEs and provides structured code context (current symbol, file type, open symbols, diagnostics) that no voice tool currently consumes.

**Why Critical (Not Just Major)**

[HYPOTHESIS] Developers are the highest-value user cohort for a power-user voice daemon: they spend the most time typing, are most willing to learn new interaction patterns, and have the highest pain from repetitive strain. If YazSes cannot solve voice coding better than generic dictation tools, it loses its primary differentiation for this cohort. [HYPOTHESIS] Code-aware context injection is the one YazSes capability that cloud tools cannot replicate without a local agent — because LSP context is local, private, and requires OS-level integration to read.

**Opportunity Scope**

[HYPOTHESIS] YazSes implements a Language Server Protocol client that reads the active file's language, cursor position, surrounding symbols, and open diagnostics, and injects this as a structured context block into the faster-whisper transcription prompt (via a custom initial prompt). This improves transcription of code-specific vocabulary (function names, variable names, symbol characters) without requiring a code-specific ASR model. Combined with the grammar classifier's per-editor profiles, YazSes becomes the most capable voice coding tool available — and the only one that works offline.

---

### gap-003: No Desktop Voice Daemon Integration for EMG Silent Input

**Problem Statement**

[EVIDENCE src-005] EMG-based silent speech command recognition in headphone form factor achieves 96% accuracy on a 10-word vocabulary. [EVIDENCE src-006] Full-text sEMG input with transformer decoder achieves 10% personalised CER. [EVIDENCE src-007] Sentence-level EEG+EMG fusion for AAC users is demonstrated in wearable hardware. [EVIDENCE src-011] The Interspeech 2025 community has formally recognised biosignal-enabled speech as a mature research direction. Despite all this, there is no open-source desktop voice daemon that exposes an EMG/biosignal input backend. The gap is entirely in the integration layer between the research hardware and the user's computer.

**Confirming Sources**

- [EVIDENCE src-005] Headphone EMG: high accuracy in consumer form factor; output is a discrete command label — directly IPC-mappable.
- [EVIDENCE src-006] Transformer sEMG: full-text output compatible with existing injection pipeline.
- [EVIDENCE src-011] Interspeech 2025 session: community validation that this direction is real and moving toward deployment.
- [HYPOTHESIS] Consumer EMG headphones (from Meta, Snap/Nextmind successors, or specialist vendors) will be available at consumer prices within 2–3 years.

**Why Critical (Not Just Major)**

[HYPOTHESIS] This gap is critical specifically for two user populations: (1) open-office workers who cannot speak aloud and currently have no voice interface available; (2) users with motor or speech disabilities who cannot use acoustic speech reliably. For these users, there is currently no viable path from "I want to use a voice daemon" to "I can use a voice daemon." [HYPOTHESIS] YazSes is the only offline voice daemon with a pluggable hardware backend architecture (HotkeyBackend protocol) that could accommodate EMG input without changing the core daemon — making it structurally closer to solving this gap than any other tool.

**Opportunity Scope**

[HYPOTHESIS] YazSes implements an EMGBackend that satisfies the HotkeyBackend protocol and maps EMG command labels to IPC method calls. For the first release, the backend ships as a hardware-agnostic stub with a documented serial/USB protocol that EMG device manufacturers can target. As specific consumer devices ship (Meta EMG wristband, OpenBCI headset), device-specific drivers are added. This positions YazSes as the open-source integration layer for the emerging EMG input ecosystem, with zero changes required to the daemon core.

---

## Major Gaps (Summary)

- **[gap-004] Gaze+voice without eye-tracking hardware** — [EVIDENCE src-001, src-004, src-010] The entire gaze+voice research field requires dedicated eye-tracking hardware, while the most common command disambiguation benefit (what is the user referring to?) can be provided by the OS accessibility tree on standard hardware. [HYPOTHESIS] YazSes context injection layer reads AT-SPI2/macOS Accessibility APIs to provide a "soft gaze" signal — active window, focused element, selected text — that is injected into the LLM intent prompt. This is a low-effort high-impact feature (2–3 days of engineering) that replicates the most studied multimodal HCI pattern at zero hardware cost.

- **[gap-005] Gaming voice protocol: no offline middleware layer** — [EVIDENCE src-008, src-009] Emotion-aware NPC dialogue from player voice is validated as engagement-positive but requires per-game custom implementation. [HYPOTHESIS] YazSes "gaming mode" defines a JSON event protocol: `{text, valence, arousal, command_intent, confidence, timestamp}` — emitted by the daemon over the existing IPC channel. Game engines integrate once to the protocol; YazSes handles all audio processing. The SER module (wav2vec2 fine-tune, ~50 MB) runs in parallel with faster-whisper within the transcription pipeline.

- **[gap-006] AAC users have no offline desktop voice daemon** — [EVIDENCE src-011, src-012] AAC research is active and AI-driven communicative movement interpretation is validated, but all current AAC solutions are proprietary devices separate from the desktop OS. [HYPOTHESIS] YazSes "AAC mode" combines: (1) acoustic STT for users with dysarthric speech; (2) EMG silent input (gap-003 solution); (3) camera-based gesture/gaze via MediaPipe for users without usable speech or muscle control. All three routes use the same injection and dispatch pipeline. This is the most comprehensive accessibility offering available in an open-source voice tool.

- **[gap-007] Dysarthric and atypical speech unsupported** — [EVIDENCE src-002] VoiceBench shows state-of-the-art models degrade significantly on accented and disfluent speech. [EVIDENCE src-011] Speech restoration is one of Interspeech 2025's featured tracks. [HYPOTHESIS] YazSes' existing enrollment wizard can be extended to collect 50–100 utterances for LoRA fine-tuning of the faster-whisper encoder — producing a personalised model that runs on the same hardware with the same latency. This would make YazSes the only voice tool with offline personalised acoustic model support.

- **[gap-008] Ambient/proactive voice mode does not exist offline** — [HYPOTHESIS] Always-on voice interfaces (Siri, Google Assistant) are cloud-connected by design. An offline ambient mode using a local wake-word detector (openWakeWord, ~2 MB, < 5% CPU) that hands off to faster-whisper on trigger would be unique in the open-source voice space. The YazSes state machine already has a LOADING → IDLE transition; ambient mode adds a LISTENING background state that continuously runs the wake-word detector and transitions to RECORDING on match.

---

## Opportunity Map

| gap_id | title | severity | opportunity_score | scoring_rationale |
|--------|-------|----------|:-----------------:|-------------------|
| gap-001 | Offline LLM intent routing | critical | 5 | [HYPOTHESIS] Largest addressable market (all power-user voice daemon users), no viable offline alternative, directly unlocks natural language commands without cloud. YazSes architecture makes this uniquely achievable offline. |
| gap-002 | Code-aware voice dictation | critical | 5 | [HYPOTHESIS] Developers are the highest-value, most motivated user cohort. LSP integration is local/offline by design. No competitor can replicate this without OS-level access. Unique moat. |
| gap-003 | EMG silent input backend | critical | 5 | [HYPOTHESIS] Only 2-3 years from consumer hardware availability. Zero code changes to daemon core. Opens entirely new user populations (open-office, disability). First-mover advantage in open-source EMG integration. |
| gap-004 | Soft gaze via OS accessibility | major | 4 | [HYPOTHESIS] Low engineering cost (2–3 days), high impact, replicates the most-studied HCI pattern at zero hardware cost. Enables XR-style interaction on standard desktop. |
| gap-005 | Gaming voice protocol | major | 4 | [HYPOTHESIS] Growing gaming market. Emotion-aware NPCs proven to increase engagement. Standardised offline middleware creates new distribution channel. No current competition. |
| gap-006 | AAC mode for desktop | major | 4 | [HYPOTHESIS] Underserved population with high unmet need. Morally compelling differentiator. Open-source AAC integration has no current competitor on desktop. |
| gap-007 | Personalised model for dysarthria | major | 3 | [HYPOTHESIS] High user impact for target population but smaller total addressable market. LoRA fine-tuning infrastructure requires significant engineering; not differentiated from upcoming cloud personalization features. |
| gap-008 | Ambient offline mode | major | 3 | [HYPOTHESIS] Compelling UX but privacy-conscious users may not want always-on audio even offline. openWakeWord integration is low effort; the main risk is false-activation UX. |
| gap-009 | Voice error correction protocol | minor | 2 | [HYPOTHESIS] Nice-to-have UX improvement. Workaround (re-speaking the command) exists and is adequate. Infrastructure exists in YazSes already. Low engineering cost but limited differentiation value. |

### Recommended Focus Areas

[HYPOTHESIS] The three critical gaps (gap-001, gap-002, gap-003) are the recommended starting points because they each open a distinct user population with no viable current alternative: gap-001 unlocks natural language commands for all users, gap-002 unlocks the developer cohort specifically, and gap-003 opens new hardware modalities and disability use cases. These three together define a v0.4 milestone that would make YazSes qualitatively different from every other voice tool on the market.

[HYPOTHESIS] Gap-001 (offline LLM routing) should be implemented first because it is a prerequisite for gap-002 (the LLM receives the code context) and is the most broadly applicable across all user cohorts. The grammar classifier becomes the fast path within the LLM routing stack rather than being replaced by it. Gap-002 (code-aware dictation) should follow immediately because it is the primary differentiation for the developer cohort and requires gap-001's LLM layer. Gap-003 (EMG backend) can be developed in parallel with gap-001/002 since it requires no changes to the daemon core — only a new HotkeyBackend implementation.

### Sequencing Constraints

- **gap-002 depends on gap-001**: code-aware context injection only provides full value when the LLM intent layer is present to consume the context. The LSP integration can be built without gap-001, but its output will be unused until the LLM layer exists. [HYPOTHESIS]
- **gap-004 (soft gaze) depends on gap-001**: the OS accessibility context block is only useful when an LLM can reason about it. Rule-based intent classification cannot consume free-form context text. [HYPOTHESIS]
- **gap-005 (gaming protocol) depends on gap-001**: emotion annotation + LLM command routing are the two components of the gaming protocol; gap-001 provides the second component. [HYPOTHESIS]
- **gap-003, gap-006, gap-007, gap-008 are independent** of gap-001 and can be pursued in parallel. [HYPOTHESIS]

---

*Study: [[yazses-future-voice-hci/input/research_scope|yazses-future-voice-hci]]*
