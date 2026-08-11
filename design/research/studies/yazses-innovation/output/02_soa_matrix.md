---
id: "soa-matrix-yazses-innovation"
title: "YazSes Innovation — State-of-the-Art Matrix"
type: soa_matrix
scenario: yazses-innovation
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
---

## State-of-the-Art Matrix

Eight dimensions evaluated across all 16 sources. Cells use:
- ✓ = demonstrated / solved / well-supported
- ~ = partial / in-progress / workaround available
- ✗ = absent / unsupported / no evidence
- ? = unclear / not disclosed

| Source | D1: Streaming / Partial Hypothesis | D2: SSH / Remote Forward | D3: Code Awareness | D4: Disfluency Handling | D5: Accessibility (Atypical Speech) | D6: AR/VR/XR Integration | D7: Gaming / 3D Nav | D8: LLM Intent Refinement |
|---|---|---|---|---|---|---|---|---|
| src-001 faster-whisper | ~ (chunk callbacks only) | ✗ | ✗ | ✗ | ~ (architecture allows fine-tune) | ✗ | ✗ | ✗ |
| src-002 whisper_streaming | ✓ (LocalAgreement, 380–520ms) | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| src-003 Macháček et al. 2023 | ✓ (formal algorithm) | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| src-004 WhisperPipe 2026 | ✓ (89ms median, consensus engine) | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| src-005 WhisperX | ~ (post-hoc word timestamps) | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| src-006 Serenade | ~ (low latency but not partial) | ✗ | ✓ (coding grammar) | ~ (limited) | ✗ | ✗ | ✗ | ~ (custom commands) |
| src-007 Talon Voice | ✓ (real-time, full commands) | ✗ | ✓ (10k+ commands) | ~ (filler noise suppression) | ✓ (RSI, motor disability) | ✗ | ✗ | ✗ |
| src-008 Voiceitt | ✗ | ✗ | ✗ | ✓ (atypical speech model) | ✓ (ALS, Parkinson's, dysarthria) | ✗ | ✗ | ✗ |
| src-009 ASR Deep Dive 2025 | ~ (streaming options surveyed) | ✗ | ~ (domain adaptation noted) | ~ (post-processing noted) | ✗ | ✗ | ✗ | ✗ |
| src-010 Adaptive XR 2025 | ~ (latency discussed) | ✗ | ✗ | ✗ | ✗ | ✓ (adaptive routing) | ~ (object selection) | ✓ (LLM routing) |
| src-011 VR Voice 2025 | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ (architecture) | ✓ (3D object interaction) | ~ (intent classification) |
| src-012 ASR Voice Agents 2026 | ✗ | ✗ | ~ (WER on tech vocab) | ✓ (disfluency analysis) | ~ (OOD robustness) | ✗ | ✗ | ~ (LLM correction noted) |
| src-013 Superwhisper | ✓ (floating overlay, partial) | ✗ | ~ (per-app profiles) | ✓ (LLM cleanup) | ✗ | ✗ | ✗ | ✓ (LLM post-process) |
| src-014 XR Survey 2025 | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ (multimodal fusion) | ~ (voice for text only) | ✗ |
| src-015 A2-LLM 2026 | ~ (180ms GPU E2E) | ✗ | ✗ | ✗ | ✗ | ✓ (avatar pipeline) | ✓ (avatar control) | ✓ (prosody + language) |
| src-016 Non-native ASR 2025 | ✗ | ✗ | ✗ | ✓ (correction reduces WER 12pp) | ✓ (non-native models) | ✗ | ✗ | ✗ |

---

## Cross-Source Analysis by Dimension

### D1: Streaming / Partial Hypothesis Display

**Consensus:** Streaming Whisper is solved at the research level (src-002, src-003, src-004). Three independent systems implement it with latency ranging from 89 ms (WhisperPipe GPU) to 520 ms (whisper_streaming CPU). [EVIDENCE src-002] [EVIDENCE src-003] [EVIDENCE src-004]

**Conflict:** No source achieves <200 ms on CPU alone — the XR/gaming threshold (src-014) is not reachable with current CPU-only approaches. [EVIDENCE src-004] [EVIDENCE src-014] [HYPOTHESIS: CPU+quantization improvements may close this gap by 2027]

**Absence:** No source describes a streaming system that also performs real-time correction of previously emitted text. Partial display + correction-on-commit is an unsolved integration problem. [NO EVIDENCE in any source]

### D2: SSH / Remote Session Forwarding

**Consensus:** No source addresses this problem at all. All voice tools assume local audio capture and local text injection. [NO EVIDENCE in any source]

**Conflict:** N/A — universal gap.

**Absence:** Zero evidence for any tool that: (a) captures audio on the local machine, (b) transcribes locally, (c) forwards resulting text to a remote shell session, and (d) maintains session awareness (which remote terminal is focused). [NO EVIDENCE] [HYPOTHESIS: This is a genuinely unoccupied product space as of 2026]

### D3: Code Awareness

**Consensus:** Two tools (Serenade, Talon) provide code-specific command grammars. [EVIDENCE src-006] [EVIDENCE src-007] Both separate ASR from command dispatch, confirming the architecture is viable.

**Conflict:** Serenade uses a dedicated speech-to-code model (not general ASR). Talon uses a general ASR engine + grammar rules. Talon's approach is more composable with YazSes's existing stack. [EVIDENCE src-006] [EVIDENCE src-007]

**Absence:** No source describes adding code awareness to an existing dictation daemon without replacing the ASR layer. No lightweight intent classifier for coding actions is published as a standalone module. [NO EVIDENCE]

### D4: Disfluency Handling

**Consensus:** Whisper omits disfluent segments in 11.86% of cases (src-012) and generates them incorrectly in 3.48% of cases (src-016). LLM-based post-processing (src-013) and dedicated correction models (src-016) both reduce this. [EVIDENCE src-012] [EVIDENCE src-013] [EVIDENCE src-016]

**Conflict:** src-013 (Superwhisper) applies LLM cleanup as a post-processing step (cloud LLM implied), while src-016 suggests a dedicated correction model. The two approaches differ on latency and offline viability. [EVIDENCE src-013] [EVIDENCE src-016]

**Absence:** No source describes a disfluency handler that works offline, adds <50 ms latency, and is lightweight enough for embedded daemon use. [NO EVIDENCE]

### D5: Accessibility (Atypical Speech)

**Consensus:** Voiceitt (src-008) and non-native ASR research (src-016) both confirm that personalised models significantly reduce WER for atypical speech. [EVIDENCE src-008] [EVIDENCE src-016] Talon is used by RSI/motor-disability users (src-007) but assumes standard speech.

**Conflict:** src-008 requires 50–200 training utterances per user; src-016 shows general-purpose fine-tuning adds 12 WER points of improvement without personalisation. [EVIDENCE src-008] [EVIDENCE src-016]

**Absence:** No open-source, offline, lightweight atypical-speech adaptation pipeline for Whisper exists as a packaged tool. [NO EVIDENCE] [HYPOTHESIS: This is a significant accessibility gap]

### D6: AR/VR/XR Integration

**Consensus:** Three sources (src-010, src-011, src-014) address XR voice. All recommend decoupling the ASR service from the XR render thread via WebSocket or IPC. [EVIDENCE src-010] [EVIDENCE src-011] [EVIDENCE src-014] The <200 ms latency threshold for real-time XR is established. [EVIDENCE src-014]

**Conflict:** src-010 finds LLM routing adds ~800 ms for complex commands — violating the <200 ms threshold. The hybrid routing strategy partially resolves this by keeping simple commands on the fast path. [EVIDENCE src-010]

**Absence:** No source describes a production-ready, offline, cross-platform voice daemon exposing a WebSocket JSON-RPC API suitable for XR integration. [NO EVIDENCE]

### D7: Gaming / 3D Navigation

**Consensus:** src-011 and src-015 both address 3D object interaction via voice. src-011 uses intent classification for object selection/manipulation. [EVIDENCE src-011] [EVIDENCE src-015]

**Conflict:** src-011 identifies 20–30% relative WER degradation from headset microphones. src-015 is GPU-only (180ms), not viable for offline-CPU constraint. [EVIDENCE src-011] [EVIDENCE src-015]

**Absence:** No source describes a gaming voice control layer that works with an external daemon (rather than in-engine code), is offline, and supports cross-engine SDKs (Unity + Unreal). [NO EVIDENCE]

### D8: LLM Intent Refinement

**Consensus:** Three sources (src-010, src-013, src-015) use LLMs to improve voice intent quality. The benefit is clear: src-013 shows LLM cleanup visibly improves dictation output. [EVIDENCE src-010] [EVIDENCE src-013] [EVIDENCE src-015]

**Conflict:** src-010 and src-013 both imply cloud LLM use. src-010's hybrid routing (LLM only when needed) partially addresses latency. [EVIDENCE src-010] [EVIDENCE src-013]

**Absence:** No source describes an offline-first LLM intent layer using a local model (e.g., llama.cpp, Ollama) that is integrated into a voice daemon's injection pipeline with sub-200 ms budget for the fast path. [NO EVIDENCE]

---

## Summary of Evidence Density

| Dimension | Sources with ✓ | Sources with ~ | Sources with ✗ | Evidence Quality |
|---|---|---|---|---|
| D1 Streaming | 4 | 4 | 8 | HIGH — 3 independent implementations |
| D2 SSH/Remote | 0 | 0 | 16 | NONE — universal gap |
| D3 Code Aware | 2 | 3 | 11 | MEDIUM — 2 products, no module |
| D4 Disfluency | 3 | 3 | 10 | MEDIUM — identified problem, partial solutions |
| D5 Accessibility | 3 | 2 | 11 | MEDIUM — commercial solutions, no open source |
| D6 AR/VR/XR | 3 | 1 | 12 | MEDIUM — research, no production tools |
| D7 Gaming/3D | 2 | 2 | 12 | LOW-MEDIUM — early research only |
| D8 LLM Intent | 3 | 2 | 11 | MEDIUM — cloud-dependent solutions only |
