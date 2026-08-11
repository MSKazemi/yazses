# ADR-v2-004 — Context-Primed Dictation & Commanding

**Status:** Accepted (2026-07-02) · Wave A
**Context links:** [[adr-v2-000-interaction-layer]], [[adr-v04-002-lsp-context]] (LSP context), [[adr-011]] (offline/no-storage)

## Context

Whisper accuracy improves markedly when its `initial_prompt` carries domain terms. YazSes
already primes the app name + personal vocab + LSP symbols via the
`_effective_initial_prompt` chokepoint. The ambient research
(internal) shows proactive context capture (ContextAgent)
works, and crucially that the "when to act" trigger can be **non-LLM** and driven by cheap,
already-consented desktop signals (active window title, current selection, clipboard) —
avoiding both sensors and the cloud.

## Decision

Automatically compose per-burst context, opt-in and never stored:
1. **Context sources (all local, read at decode time, discarded after):** active window
   title, current text selection, clipboard, and (when the LSP bridge is active) nearby
   editor symbols. Merged into `initial_prompt` through the existing chokepoint.
2. **Deictic command resolution:** commands referencing "this/that/here/above" are resolved
   against the same context (e.g. selection or LSP symbol under cursor) before dispatch.
3. **Privacy controls:** each source individually toggleable; content is used transiently and
   **never written to the corpus or logs**; redaction patterns apply if it ever were.

Config: `[context] enabled=false`, `use_window_title`, `use_selection`, `use_clipboard`,
`use_lsp`. Per-OS accessors in `platform/*`; logic in `commands/context.py`.

## Consequences

- **+** Domain terms transcribed correctly with zero user effort; context-aware commands.
- **+** Reuses the `initial_prompt` chokepoint + LSP provider; non-LLM trigger keeps it light.
- **−** Reading window/selection/clipboard is sensitive → strictly local, opt-in per source,
  transient, never stored; clear documentation of exactly what is read.
- **−** Per-OS accessors vary (Wayland restricts window/selection reads) → degrade gracefully
  to whatever the platform allows.
