# ADR-v2-003 — Spoken Edit Mode (open-ended interactive dictation)

**Status:** Accepted (2026-07-02) · Wave A
**Context links:** [[adr-v2-000-interaction-layer]], [[adr-v04-001-slm-inference]] (Tier-2 SLM), command-key work (v1.2.0)

## Context

The voice-HCI research (internal) identifies editing by
voice as the weak link: the best offline tools use rigid "select X / correct Y" grammars or
require a mouse, while open-ended spoken editing (MS TERTiUS "Toward Interactive Dictation",
Rambler CHI'24 "gist manipulation") is research-only and **not available offline**. YazSes
has a Tier-1 regex grammar + optional Tier-2 SLM router and a dedicated command key.

## Decision

Add an opt-in **Spoken Edit Mode** that applies open-ended edits to recently dictated text:
1. A small set of text operations over the last-injected span / editor buffer: replace
   ("change 'their' to 'there'"), delete ("delete the last sentence"), case ("capitalize
   that"), reflow, and "respeak this". Covered by an extended grammar for the common ~20 ops.
2. **Dictate-vs-command disambiguation:** use the existing **command key** as the explicit
   signal (held → edit command, not literal text), avoiding the segmentation ambiguity that
   makes fully-implicit interactive dictation hard. Optional Tier-2 SLM handles fuzzier
   phrasings when confidence is low.
3. **Destructive-op guard:** deletes/replaces over multi-word spans require a quick confirm
   (spoken or overlay), per the human-in-the-loop invariant.

Config: `[commands] spoken_edit=false` (+ reuse existing `slm_*`). Lives in `commands/`
(new `edit_ops.py`) wired into `dispatch.py`.

## Consequences

- **+** Removes the biggest time-sink for hands-free users (fixing without a mouse); offline
  parity with cloud "interactive dictation" research.
- **+** Reuses grammar + SLM router + command key; incremental.
- **−** Ambiguity (content vs command) → mitigated by the command-key signal + confirm guard.
- **−** Editor-buffer editing needs a target (last-injected span, or editor bridge) → start
  with last-span operations; deepen via LSP/editor bridges where present.
