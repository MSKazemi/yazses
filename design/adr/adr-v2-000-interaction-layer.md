# ADR-v2-000 — YazSes v2: the Voice-First Interaction Layer (umbrella)

**Status:** Accepted (2026-07-02)
**Context links:** [[adr-011]] (zero telemetry / offline), [[adr-012-self-improvement-loop]] (encrypted corpus), [[adr-013-llm-cleanup]] (guarded text-transform philosophy), [[adr-014-tune-holdout-validation]] (held-out promotion gate), [[adr-v04-001-slm-inference]] (SLM tier), [[adr-v04-002-lsp-context]] (editor context)

## Context

v1.4.1 is a stable, well-adopted **offline dictation + voice-command** daemon. The
2026-07 state-of-the-art sweep (an internal design note, five evidence-anchored
domains) found that the industry shipped all the ingredients for a richer voice-first
interaction layer — on-device SLMs (Apple Foundation Models, Phi Silica, Gemini Nano),
the MCP tool standard, consumer sEMG/gaze wearables (Meta Neural Band, Vision Pro),
atypical-speech ASR (Speech Accessibility Project), and "draft-then-polish" dictation
(Fluid Dictation, Gboard Rambler) — **but tied them to the cloud or a walled garden.**
Microsoft Recall's backlash and the Rewind→Limitless→Meta collapse show the market is
retreating toward "provably never leaves your machine," which is exactly YazSes's posture.

The synthesis (an internal design note) defines 13 features
(10 flagship + 3 experimental) that are novel, on-device, and genuinely useful.

## Decision

Open the **v2.0.0 line** as an additive interaction layer over the v1 pipeline. Governing
invariants (binding on every v2 feature):

1. **On-device only** — no cloud, no API key, no telemetry (extends ADR-011).
2. **Off by default & dependency-isolated** — pure logic is dependency-free; heavy backends
   import lazily behind optional extras; each feature is a `yazses features` capability.
   Experimental features refuse `enable` without `--force`.
3. **Consent-first data** — captured content lives only in the encrypted machine-bound
   corpus (ADR-012); redaction + retention honored; biometrics never plaintext.
4. **Human-in-the-loop for side effects** — any state-changing action needs spoken/visual
   confirmation. This also engineers around the documented sub-50-step agent-reliability
   cliff (OSWorld-Human): keep voice actions short, verifiable, confirmable.
5. **Cross-platform** — Linux-first where OS APIs differ, but no feature is macOS-only.

Delivery in three waves, each its own ADR(s):
- **Wave A (P0, current stack):** Confidence Ink ([[adr-v2-001-confidence-ink]]), Prosody
  Auto-Format ([[adr-v2-002-prosody-autoformat]]), Spoken Edit Mode
  ([[adr-v2-003-spoken-edit-mode]]), Context-Primed Dictation
  ([[adr-v2-004-context-primed-dictation]]).
- **Wave B (P1):** Spoken Recall, Voice-to-Tool (Spoken MCP), AT-SPI Voice Pilot, True
  Code-Switch, Personal Speech Adapter.
- **Wave C (EXP):** Gaze-Routed Dictation, sEMG Command Layer + Modality Router,
  Accessibility Continuum, Glasses↔Desktop Bridge.

The `v2.0.0-dev` tag is cut **only when Wave A code + tests land**, so a tag always points
at working code (the current well-working v1.4.1 is the preserved fallback baseline).

## Consequences

- **+** A defensible, privacy-first position no cloud vendor can match; strong job-showcase
  narrative (research-grounded, ADR-disciplined, incremental).
- **+** Reuses existing modules (slm_router, corpus, gaze/zones, polyglot/lid, LSP context,
  overlay, tts, remote/agent, personalize) — most features are integration, not greenfield.
- **−** Surface-area growth and optional-dependency matrix complexity → mitigated by the
  off-by-default + `features` registry discipline and dependency isolation.
- **−** Some features (Personal Adapter, AT-SPI on Wayland, webcam gaze accuracy) carry real
  feasibility risk → each ADR states a fallback and, where relevant, a measurement gate
  before shipping.
