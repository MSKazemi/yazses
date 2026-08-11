# ADR-v2-078 — Verbatim ⇄ Autoformat Live Toggle

**Status:** Accepted (2026-07-02) · Wave J
**Context links:** [[adr-v2-048-entity-itn]] (what gets toggled off), [[adr-v2-047-field-aware-dictation]], [[adr-011]]

## Context

Wave J research (#3) — two reserved phrases flip a per-burst flag (like the existing
`_command_mode`): "dictate verbatim" freezes all ITN / voice-punctuation / reflow and injects the
literal lexical form ("one hundred dollars"); "resume formatting" restores the pipeline — mid-burst,
no stop. Essential for code identifiers, quotes, spoken-aloud passwords, legal capture. No existing
feature exposes a runtime ITN on/off switch. Anchors: Azure Speech "Display text formatting"
(production lexical-vs-ITN toggle), arXiv 2505.24229 (context-gated separable ITN, 2025).

## Decision

Add an opt-in **Verbatim⇄Autoformat Toggle**: `[verbatim] enabled=false`. Pure cores:
`detect_mode_command(text)` recognizes the reserved phrases → `"verbatim"` / `"auto"` (else None),
and `VerbatimGate` holds the mode: `handle_command(text)` consumes a mode phrase, `is_verbatim()`
tells the pipeline whether to bypass all formatting for the current burst. Dependency-free; the
daemon consults `is_verbatim()` to skip ITN/punctuation/reflow. OFF by default.

## Consequences

- Runtime control over how much the pipeline transforms — verbatim mode is strictly *less*
  transformation.
- Pure state machine over the existing pipeline; no model.
- Distinct — the only runtime ITN on/off switch.
- Privacy (ADR-011): pure local routing.
- Caveat: mode is per-session state the daemon must thread into the dictate path; the pure gate is
  off by default until wired.
