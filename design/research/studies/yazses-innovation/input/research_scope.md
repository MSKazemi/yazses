---
id: "scope-yazses-innovation"
title: "YazSes Innovation Roadmap — Research Scope"
type: research_scope
status: approved
scenario: "yazses-innovation"
created_at: 2026-05-14
updated_at: 2026-05-14
sources:
  - src-001
  - src-002
  - src-003
  - src-004
  - src-005
  - src-006
  - src-007
  - src-008
  - src-009
  - src-010
  - src-011
  - src-012
  - src-013
  - src-014
  - src-015
  - src-016
confidence: high
owner: "Mohsen Seyedkazemi Ardebili"
next_action: "Proceed to Stage 2: ResearchCards"
---

## Topic

**YazSes Innovation Roadmap: Cross-Platform Offline Voice Dictation — Next-Generation Capabilities.**

YazSes is a cross-platform, offline hold-to-talk voice dictation daemon (Linux/macOS/Windows) powered by `faster-whisper` (CPU int8, no cloud dependency). While the v0.2.x baseline delivers reliable offline dictation via a hotkey daemon and text injection, seven major opportunity domains remain unexploited: (1) voice input over SSH and remote sessions, (2) streaming transcription with real-time partial display and self-correction, (3) code-aware voice commands for programmers, (4) accessibility for users with motor and speech impairments, (5) AR/VR/XR spatial computing voice interaction, (6) gaming and 3D environment voice control, and (7) LLM-assisted intent refinement. This research pack tests the premise that a single lightweight, offline-first daemon — extended with a minimal set of protocol adapters and UX layers — can address all seven domains without requiring cloud ASR or GPU inference.

## Research Questions

1. **Can voice audio be proxied from a local microphone to a remote SSH session's text injector with acceptable latency (<500 ms)?** [HYPOTHESIS] Yes — audio capture stays local; only transcribed text is forwarded over the SSH control channel or a side-channel socket.

2. **Can faster-whisper be adapted to emit partial (streaming) hypotheses during speech, enabling real-time character-by-character display with sub-word correction?** [HYPOTHESIS] Yes — using a LocalAgreement streaming policy (two-pass confirmation), partial text can be displayed within 100–400 ms of utterance with correction on commit.

3. **What is the minimum command grammar required to give a programmer voice control over code-editing actions (navigate, insert, delete, refactor) without requiring a dedicated coding ASR model?** [HYPOTHESIS] A lightweight intent classifier on top of the existing STT output, with a ~100-rule grammar for code verbs, is sufficient for 80% of common coding actions.

4. **How should YazSes handle disfluencies (filler words, repetitions, self-corrections) to produce clean dictated text?** [HYPOTHESIS] Post-processing with a small LLM or rule-based correction layer, applied before text injection, reduces WER artifacts without noticeable latency increase.

5. **What accessibility profile adaptations are needed to make YazSes usable for people with atypical speech (ALS, Parkinson's, dysarthria)?** [HYPOTHESIS] Custom acoustic model fine-tuning on atypical speech (personalized Whisper fine-tune), plus configurable silence detection thresholds and hold-key alternatives, are the key enablers.

6. **What integration surface does YazSes need to function as a voice input layer for AR/VR/XR headsets and games?** [HYPOTHESIS] A WebSocket server exposing a JSON-RPC event stream of transcribed text/intents, consumable by Unity, Unreal Engine, and web-based XR frameworks.

7. **Can an LLM-based adaptive routing layer decide whether raw STT output or LLM-refined intent is injected, without breaking the offline-first constraint?** [HYPOTHESIS] Yes — local LLM (e.g., Ollama/llama.cpp) can handle the routing decision; cloud fallback is opt-in, not required.

## Inclusion / Exclusion Criteria

**Inclusion criteria** — a source must satisfy ALL of:

- Addresses voice input, ASR, speech recognition, accessibility, XR interaction, or coding voice control
- Has a public URL, open paper, or maintained repo/product page
- Published or last-updated on or after 2021-01-01
- Provides technical substance (architecture, benchmarks, code, or documented API)

**Exclusion criteria** — a source is excluded if ANY of:

- Purely cloud-based ASR with no offline mode (Deepgram, AssemblyAI standalone) — unless used for competitive comparison
- Vendor marketing material with no technical architecture disclosed
- Duplicate of another source with no additional contribution
- Gaming/XR sources that cover spatial audio only, with no voice input component

## Source Taxonomy

| Source type | Target count | Rationale |
|-------------|--------------|-----------|
| paper       | 7            | Academic ground-truth on ASR streaming, disfluency, XR voice |
| repo        | 3            | Production-grade reference implementations (faster-whisper, whisper_streaming, WhisperX) |
| product     | 4            | Competitive landscape (Serenade, Talon, Superwhisper, Voiceitt) |
| blog        | 1            | Current practitioner state-of-the-art summary |
| docs        | 0            | Covered by repo READMEs |
| standard    | 0            | No relevant standards within scope |
| **Total**   | **16**       | Covers all 7 research domains with 2+ sources per domain |

## Search Plan

Sources were gathered via parallel web search across seven domains: (a) SSH/remote voice forwarding, (b) streaming Whisper/VAD architectures, (c) voice coding tools, (d) accessibility AAC tools, (e) AR/VR/XR voice, (f) gaming voice commands, (g) metaverse/avatar voice control. Seed queries included "faster-whisper streaming", "whisper streaming partial hypothesis", "Talon voice coding", "Voiceitt atypical speech", "Apple Vision Pro voice input", "voice commands 3D VR", "adaptive speech interface XR". The source set evolved from initial GitHub repos toward a mix of papers and products as coverage of XR and accessibility domains required more recent academic sources.

**Seed queries / keywords:**
- "faster-whisper streaming VAD realtime"
- "whisper_streaming LocalAgreement partial hypothesis"
- "Serenade voice coding open source"
- "Talon voice hands-free programming"
- "Voiceitt non-standard speech AAC"
- "Apple Vision Pro voice input XR"
- "adaptive speech interfaces XR LLM"
- "voice commands 3D object interaction VR"
- "A2-LLM avatar voice metaverse"
- "SSH terminal voice forwarding dictation"

## Target Users

1. **Software developers with repetitive strain injury (RSI) or motor disabilities** — currently using Talon Voice or Dragon NaturallySpeaking but lack an offline, Linux-native alternative with code-aware commands. They need precise, low-latency dictation that understands code structure, runs entirely on-device, and integrates with their terminal workflow. [HYPOTHESIS]

2. **Remote server operators and DevOps engineers** — connect to remote machines via SSH or VS Code Remote SSH daily; cannot use desktop dictation tools because the dictation app has no awareness of what terminal is "active" on the remote host. They need voice input that follows the terminal's focus regardless of network topology. [HYPOTHESIS]

3. **People with ALS, Parkinson's, dysarthria, or other speech/motor impairments** — need an offline dictation tool that can be fine-tuned to atypical speech patterns without sending audio to cloud services (privacy constraint). [HYPOTHESIS]

4. **XR/game developers and players** — building or playing in Unity/Unreal 3D environments; want voice commands to control game objects, navigate 3D worlds, or dictate in-game text without internet dependency. [HYPOTHESIS]

## Scope Boundaries

**IN SCOPE:**
- Streaming ASR with partial hypothesis display and self-correction on the local machine
- SSH/remote session voice forwarding protocol design
- Code-aware command grammar on top of existing STT pipeline
- Accessibility adaptations: silence threshold, hold-key alternatives, atypical speech tolerance
- AR/VR/XR integration via WebSocket JSON-RPC event server
- Gaming voice command layer (object selection, navigation, text input in 3D)
- LLM-assisted post-processing (local, offline) for intent classification and disfluency removal
- Linux, macOS, Windows support — maintaining offline-first constraint

**OUT OF SCOPE (explicitly):**
- Cloud-only ASR replacements — YazSes's offline constraint is a hard product requirement; this pipeline does not investigate replacing faster-whisper with a cloud API
- Full speaker diarization — multi-speaker meeting transcription is a different product vertical
- Real-time translation (speech-to-foreign-language-text) — out of scope for this roadmap cycle
- Building a full XR runtime or game engine — YazSes is a voice input layer only; XR engine development is out of scope
- Training custom acoustic models from scratch — fine-tuning existing Whisper weights is in scope; training from zero is not

## Output Goal

A successful Stage 1 produces:

- **16 ResearchCards** (one per source) with every claim tagged `[EVIDENCE src-NNN]`, `[HYPOTHESIS]`, or `[TODO: find source]`.
- **One SoAMatrix** comparing sources across 8 dimensions: streaming latency, offline capability, disfluency handling, SSH/remote support, code-awareness, accessibility adaptation, XR/gaming integration, correction/rollback.
- **One GapAnalysis** identifying ≥8 gaps, with ≥2 critical-severity gaps, each aligned to one of the four target user personas above.

**Human review gate (after Stage 1):** A reader unfamiliar with YazSes can read the gap analysis and identify which 2–4 gaps justify the next implementation sprint. If the gap analysis does not produce that legibility, the research pack has failed.
