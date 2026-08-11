---
id: "gap-analysis-yazses-innovation"
title: "YazSes Innovation — Gap Analysis"
type: gap_analysis
scenario: yazses-innovation
created_at: 2026-05-14
updated_at: 2026-05-14
source_matrix: "output/02_soa_matrix.md"
confidence: high
---

## Gap Analysis

Gaps derived from all `[NO EVIDENCE]` cells and inter-source conflicts in `02_soa_matrix.md`. Each gap is assigned a severity (critical / high / medium) and mapped to a target persona.

---

### gap-001 — No SSH/Remote Voice Forwarding

**Severity:** CRITICAL

**Matrix cell(s):** D2 — all 16 sources score ✗

**Evidence:** No source in the research pack addresses the problem of using voice dictation when connected to a remote machine via SSH or VS Code Remote. All existing tools (Talon, Serenade, Superwhisper, YazSes) assume the microphone and the text injection target are on the same physical machine. [EVIDENCE src-001] [EVIDENCE src-007] [EVIDENCE src-013] [NO EVIDENCE for any contrary solution]

**Conflict surfaced:** None — the gap is universal.

**Opportunity:** A remote-voice protocol that: (a) captures audio on the local client, (b) transcribes via local faster-whisper, (c) forwards the transcript over an SSH socket/FIFO or WebSocket tunnel to the remote daemon, and (d) performs text injection on the remote machine. This would work with VS Code Remote SSH, tmux, mosh, and standard SSH without any agent installed on the remote server.

**Affected personas:** Remote server operators and DevOps engineers (Persona 2); Software developers with RSI/motor disability who code on remote servers (Persona 1).

**Feasibility note:** The SSH channel can carry arbitrary data via port forwarding or a control-channel socket. The transcript is small (text only, not audio). [HYPOTHESIS: latency budget for round-trip text forwarding is <50 ms on a LAN and <200 ms on WAN, well within the 500 ms acceptable threshold]

---

### gap-002 — No Streaming Partial Hypothesis Display With Correction

**Severity:** CRITICAL

**Matrix cell(s):** D1 (partial — streaming exists but no correction-on-commit)

**Evidence:** Three sources implement streaming Whisper (src-002, src-003, src-004). However, zero sources describe a streaming system that also corrects previously emitted text when the final transcript differs from the partial hypothesis. Superwhisper displays partials (src-013) but does not publicly document rollback/correction behaviour. [EVIDENCE src-002] [EVIDENCE src-003] [EVIDENCE src-004] [EVIDENCE src-013] [NO EVIDENCE for correction-on-commit in any source]

**Conflict surfaced:** src-004 (WhisperPipe) achieves 89 ms median E2E latency but requires GPU. CPU implementations (src-002) sit at 380–520 ms, exceeding the 200 ms XR threshold (src-014). [EVIDENCE src-004] [EVIDENCE src-014]

**Opportunity:** A streaming layer for YazSes that: (a) emits partial text to the focused window as the user speaks, (b) tracks cursor position of injected partial text, (c) on final commit, selects back the partial text and replaces it with the corrected final transcript. The user sees real-time typing, and corrections happen silently at sentence boundaries.

**Affected personas:** All four personas, especially developers who speak code dictation and want immediate visual feedback (Persona 1), and non-native/atypical speech users who benefit from seeing the partial to self-correct (Persona 3).

---

### gap-003 — No Code-Aware Voice Command Grammar Module

**Severity:** HIGH

**Matrix cell(s):** D3 — only 2 of 16 sources score ✓, and both are standalone products not reusable modules

**Evidence:** Serenade (src-006) and Talon (src-007) both implement code-aware command dispatch, but neither exposes a reusable grammar module. No open-source, standalone code-command classifier exists that can be layered on top of a generic STT output. ASR WER on technical vocabulary (function names, CLI flags, identifiers) is double the general-speech WER (src-009). [EVIDENCE src-006] [EVIDENCE src-007] [EVIDENCE src-009]

**Conflict surfaced:** src-006 uses a dedicated speech-to-code model (closed), while src-007 uses a grammar-rule approach (open, via Python scripts). The grammar-rule approach is more composable with YazSes. [EVIDENCE src-006] [EVIDENCE src-007]

**Opportunity:** A lightweight code-command intent classifier — a ~100-rule grammar tree mapping spoken phrases to editor/terminal API calls — that runs on top of YazSes's STT output without replacing the ASR layer. Rules like: "add function [name]" → insert function skeleton; "delete [last N words/lines]" → inject backspace sequence; "go to line [N]" → emit Ctrl+G keystroke. No GPU required.

**Affected personas:** Software developers with RSI (Persona 1); remote operators using terminal voice control (Persona 2).

---

### gap-004 — No Offline Disfluency / Self-Correction Handler

**Severity:** HIGH

**Matrix cell(s):** D4 — 3 sources have partial solutions, all require cloud LLM or GPU

**Evidence:** Whisper omits disfluencies in 11.86% of utterances (src-012) and generates spurious ones in 3.48% (src-016). Post-processing with LLM reduces this (src-013, src-016) but all demonstrated solutions use cloud APIs or GPU inference. No source describes an offline, low-latency (< 50 ms) disfluency correction module. [EVIDENCE src-012] [EVIDENCE src-013] [EVIDENCE src-016]

**Conflict surfaced:** src-013 (Superwhisper) applies LLM post-processing but is proprietary and cloud-dependent. src-016 recommends a dedicated correction model — but does not specify a lightweight deployable one.

**Opportunity:** A rule-based + small-model disfluency handler: (1) regex/pattern rules remove filler words ("um", "uh", "like", "you know", "so") before injection; (2) repeated phrase detection ("the the the function") removes repetitions; (3) self-correction detection ("delete that", "no wait", "I mean") triggers rollback. This could run in <10 ms on CPU as a pure text post-processor, with an optional local LLM (Ollama) pass for more complex corrections.

**Affected personas:** All personas, especially non-native speakers and users with atypical speech (Persona 3) where disfluencies are more frequent.

---

### gap-005 — No Open-Source Atypical-Speech Adaptation for Offline Whisper

**Severity:** HIGH

**Matrix cell(s):** D5 — only commercial solutions (Voiceitt) cover atypical speech; no open-source offline pipeline exists

**Evidence:** Voiceitt (src-008) demonstrates that personalised models (50–200 utterances) significantly improve WER for atypical speakers. src-016 shows fine-tuning reduces non-native English WER by 12 pp. However, no open-source, offline, packaged pipeline for Whisper atypical-speech adaptation exists. [EVIDENCE src-008] [EVIDENCE src-016] [NO EVIDENCE for open-source atypical-speech fine-tune pipeline]

**Conflict surfaced:** src-008 is a mobile AAC app — not a desktop dictation daemon. The personalisation approach requires either a cloud training step (Voiceitt's approach) or local fine-tuning infrastructure that most users lack.

**Opportunity:** A YazSes accessibility profile: (a) guided enrollment wizard (50 utterances, ~5 minutes), (b) local Whisper fine-tune on the enrolled audio using PEFT/LoRA (fits in 4 GB RAM), (c) the fine-tuned adapter is saved to the user's config dir and loaded at startup. Plus: configurable silence/noise thresholds, hold-key alternatives (footpedal, joystick), and adjustable chunk size for slower speech rates.

**Affected personas:** Persona 3 (ALS, Parkinson's, dysarthria users) — the highest-impact accessibility gap.

---

### gap-006 — No Production-Ready WebSocket Voice API for XR Integration

**Severity:** HIGH

**Matrix cell(s):** D6 — 3 sources describe XR voice architectures, none are implemented as a standalone offline daemon

**Evidence:** Three papers (src-010, src-011, src-014) all recommend decoupling the ASR service from the XR render thread via WebSocket. None of these papers is implemented as a production service. Apple Vision Pro (src-014) requires on-device ASR via visionOS API — no third-party offline ASR is pluggable. Meta Quest supports WebView-based apps that could consume a local WebSocket. [EVIDENCE src-010] [EVIDENCE src-011] [EVIDENCE src-014]

**Conflict surfaced:** <200 ms is required for XR real-time feel (src-014). CPU-based Whisper streaming is 380–520 ms (src-002). The gap between achievable CPU latency and the XR threshold is real. Mitigation: XR profiles use smaller models (tiny.en) and shorter chunk sizes, accepting lower accuracy.

**Opportunity:** A YazSes XR profile exposing: (a) a WebSocket server on localhost:8765 emitting JSON-RPC events (`partial_transcript`, `final_transcript`, `command_detected`), (b) a Unity SDK (C# wrapper), (c) an Unreal Engine SDK (Blueprint node), (d) a web SDK (JavaScript EventSource consumer). Game/XR developers can subscribe to the event stream and handle voice commands in their engine of choice, without embedding an ASR library.

**Affected personas:** XR/game developers (Persona 4).

---

### gap-007 — No Gaming Voice Command Layer with 3D Spatial Context

**Severity:** MEDIUM

**Matrix cell(s):** D7 — 2 sources address 3D interaction, none are daemon-level integrations

**Evidence:** src-011 demonstrates intent classification for voice-driven 3D object selection. src-015 shows voice → avatar control at 180 ms (GPU). Neither is packaged as an external service compatible with game engines. Headset microphones degrade ASR accuracy by 20–30% (src-011). [EVIDENCE src-011] [EVIDENCE src-015]

**Conflict surfaced:** src-015 requires GPU for 180 ms latency; CPU is not demonstrated for gaming contexts. [EVIDENCE src-015]

**Opportunity:** A YazSes gaming command profile: (a) recognises spatial commands ("move forward", "turn left 90", "jump", "attack", "open inventory"); (b) emits structured JSON events over WebSocket including intent type, target, direction, magnitude; (c) game-side SDK maps intents to in-engine actions. The profile is configurable per game (user-defined command vocabulary).

**Affected personas:** Persona 4 (XR/game developers); secondarily, gamers with motor disabilities who cannot use controllers (overlap with Persona 3).

---

### gap-008 — No Offline LLM Intent Routing Layer

**Severity:** MEDIUM

**Matrix cell(s):** D8 — 3 sources use LLM for intent refinement, all cloud-dependent

**Evidence:** src-010 (adaptive XR routing) and src-013 (Superwhisper LLM cleanup) both demonstrate value from LLM-based intent refinement. src-015 (A2-LLM) shows end-to-end audio-LLM reasoning. All cloud-dependent. No offline, lightweight LLM integration in a voice daemon is documented. [EVIDENCE src-010] [EVIDENCE src-013] [EVIDENCE src-015]

**Conflict surfaced:** src-010's LLM path adds ~800 ms, violating the 200 ms XR threshold. The hybrid routing solution (LLM only for ambiguous inputs) is the mitigation. [EVIDENCE src-010]

**Opportunity:** A YazSes LLM layer using Ollama (or llama.cpp): (a) rule-based router decides if transcript is simple dictation (→ inject immediately), a code command (→ dispatch via gap-003 grammar), or ambiguous/complex (→ route to local LLM for intent disambiguation); (b) the LLM is optional and user-configurable; (c) the daemon functions fully without it, just with lower intent classification on ambiguous inputs.

**Affected personas:** All personas, especially developers using code commands (Persona 1) and XR/game developers (Persona 4).

---

## Gap Summary Table

| Gap ID | Title | Severity | D-Matrix | Personas | [NO EVIDENCE] Cell |
|---|---|---|---|---|---|
| gap-001 | SSH/Remote Voice Forwarding | CRITICAL | D2 | P1, P2 | All 16 sources ✗ |
| gap-002 | Streaming + Correction-on-Commit | CRITICAL | D1 | P1, P2, P3, P4 | Correction: all 16 ✗ |
| gap-003 | Code-Aware Command Grammar Module | HIGH | D3 | P1, P2 | Reusable module: all ✗ |
| gap-004 | Offline Disfluency Handler | HIGH | D4 | P1, P2, P3, P4 | Offline <50ms: all ✗ |
| gap-005 | Atypical-Speech Adaptation Pipeline | HIGH | D5 | P3 | Open-source offline: all ✗ |
| gap-006 | WebSocket Voice API for XR | HIGH | D6 | P4 | Production offline API: all ✗ |
| gap-007 | Gaming / 3D Spatial Command Layer | MEDIUM | D7 | P4, P3 | Cross-engine daemon: all ✗ |
| gap-008 | Offline LLM Intent Routing | MEDIUM | D8 | P1, P4 | Offline daemon LLM: all ✗ |
