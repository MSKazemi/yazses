---
id: "prioritization-yazses-innovation"
title: "YazSes Innovation — Capability Prioritization Matrix"
type: prioritization_matrix
scenario: yazses-innovation
created_at: 2026-05-14
updated_at: 2026-05-14
confidence: high
---

## Scoring Methodology

All four dimensions scored 1–5. Overall priority = `(user_pain × 2) + feasibility + novelty + production_value` (max 35).
Higher = higher priority.

Recommended dispositions: **MVP** (build now, v0.3.x), **v2** (next major cycle), **reject** (deprioritise).

---

## Prioritization Table

| Cap ID | Title | User Pain (×2) | Feasibility | Novelty | Prod Value | Total | Rank | Disposition |
|---|---|---|---|---|---|---|---|---|
| cap-004 | Offline Disfluency Filter | 4 (×2=8) | 5 | 2 | 4 | **19** | 4 | **MVP** |
| cap-001 | SSH/Remote Voice Forwarding | 5 (×2=10) | 4 | 5 | 5 | **24** | 1 | **MVP** |
| cap-002 | Streaming + Correction | 5 (×2=10) | 3 | 5 | 5 | **23** | 2 | **MVP** |
| cap-003 | Code Command Grammar | 4 (×2=8) | 4 | 3 | 4 | **19** | 4 | **MVP** |
| cap-005 | Atypical-Speech Adaptation | 5 (×2=10) | 2 | 5 | 5 | **22** | 3 | **MVP** (phased) |
| cap-006 | XR Voice API / WebSocket | 3 (×2=6) | 4 | 4 | 4 | **18** | 6 | **v2** |
| cap-007 | Gaming / 3D Spatial Commands | 3 (×2=6) | 4 | 4 | 3 | **17** | 7 | **v2** |
| cap-008 | LLM Intent Routing Layer | 3 (×2=6) | 3 | 4 | 3 | **16** | 8 | **v2** |

---

## Rationale by Capability

### cap-001 — SSH/Remote Voice Forwarding — RANK 1 — MVP

Highest combined score. This is a genuine unoccupied product space (D2 had zero evidence from 16 sources). [EVIDENCE src-002] [EVIDENCE src-007] [EVIDENCE src-013] The user pain is acute and daily for remote developers and DevOps engineers. Feasibility is high: the architecture is simple (local STT + text forwarding over SSH tunnel), no new models or GPUs required. Production value is high: this is a clear differentiator from every competitor, and it unlocks VS Code Remote SSH + tmux workflows that no other voice tool supports. Novel: no existing open-source or commercial tool has implemented this.

### cap-002 — Streaming + Correction — RANK 2 — MVP

Second-highest score. User pain is universal — every dictation user benefits from seeing real-time partial text rather than waiting 1–3 seconds for a result. The LocalAgreement algorithm is proven (src-002, src-003). The correction-on-commit (rollback/replace) mechanism is not proven but has a clear implementation path using word timestamps (src-001, src-005). Feasibility is 3 (medium) because the cursor-tracking + replace sequence must be robust across different application types (terminal, browser, IDE). Production value: this is the feature users most visibly notice. Superwhisper has it on macOS (src-013); YazSes needs it on Linux.

### cap-005 — Atypical-Speech Adaptation — RANK 3 — MVP (phased)

User pain is 5 — ALS, Parkinson's, and dysarthria users have no good open-source, offline, Linux option. Voiceitt (src-008) is mobile-only and commercial. Feasibility is 2 (the LoRA fine-tune requires careful packaging and may need user guidance), so this is "MVP phased": the enrollment wizard and configurable accommodation parameters ship in MVP; the local fine-tune is v2 unless a pre-packaged LoRA training script proves straightforward. The accessibility narrative also significantly strengthens YazSes's non-profit/open-source positioning.

### cap-004 — Offline Disfluency Filter — RANK 4 (tied) — MVP

The rule-based layer (filler removal, repetition dedup, self-correction rollback) is extremely high feasibility (5) and is a pure text-processing step that adds <10 ms. [EVIDENCE src-012] It improves every user's experience immediately. The LLM-optional extension (async Ollama) can ship in the same PR as a config flag. The low novelty score (2) reflects that this is a well-known problem with known solutions — but YazSes's offline, CPU-only constraint means none of the commercial solutions (src-013) are reusable.

### cap-003 — Code Command Grammar — RANK 4 (tied) — MVP

Tied with cap-004. Code-aware commands address the primary developer persona. Feasibility is 4 — the grammar is a Python module, no new dependencies beyond `rapidfuzz` or similar. The ~100-rule grammar is documented by Talon's community knowledgebase (src-007) and Serenade's command set (src-006), so the vocabulary is already known. Novelty is 3 — this isn't novel research, but it is novel in a standalone offline daemon.

### cap-006 — XR Voice API — RANK 6 — v2

High feasibility and novelty, but user pain is lower (XR developers are a smaller and more technically capable audience). The <200 ms CPU latency gap vs the XR threshold (src-014) is a real blocker for v1. Deferring to v2 allows the streaming performance work (cap-002) to reduce latency first, making the XR API viable.

### cap-007 — Gaming Profile — RANK 7 — v2

Depends on cap-006 (WebSocket API). Gaming-specific vocabulary is straightforward but the platform integration work (Unity/Unreal SDKs) is significant. The headset microphone WER degradation problem (src-011) needs to be addressed in cap-005 first. Defer to v2.

### cap-008 — LLM Intent Routing — RANK 8 — v2

Lowest score. LLM routing adds latency and complexity for marginal gain on simple dictation (which is 80%+ of usage). The offline LLM dependency (Ollama) is a significant install barrier. The cap-003 grammar handles the clear cases; the LLM is only needed for ambiguous inputs. Defer to v2; ship only if cap-003 proves insufficient.

---

## MVP Selection — Approved Capabilities

The following capabilities are selected for the MVP (v0.3.x):

| Cap | Title | Phasing |
|---|---|---|
| cap-001 | SSH/Remote Voice Forwarding | v0.3.0 |
| cap-002 | Streaming + Correction | v0.3.0 |
| cap-003 | Code Command Grammar | v0.3.0 |
| cap-004 | Offline Disfluency Filter | v0.3.0 (rule-based path only) |
| cap-005 | Atypical-Speech Adaptation | v0.3.0 (accommodation params + enrollment wizard only; LoRA fine-tune deferred to v0.4.0) |

---

## v2 Capabilities (v0.4.x and beyond)

| Cap | Title | Prerequisite |
|---|---|---|
| cap-005 (LoRA fine-tune) | Local Whisper fine-tune for atypical speech | Enrollment wizard shipped in MVP |
| cap-006 | XR Voice API / WebSocket Server | cap-002 (streaming latency improvement) |
| cap-007 | Gaming / 3D Spatial Commands | cap-006 (WebSocket API) |
| cap-008 | LLM Intent Routing | cap-003 (grammar module) |
