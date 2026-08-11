# ADR-v2-081 — Voice Jump-to-Symbol / Structural Hop

**Status:** Accepted (2026-07-02) · Wave J
**Context links:** [[adr-v2-038-atspi-voice-pilot]] (UI elements vs code symbols), [[adr-v2-028-voice-mouse-grid]] (blind grid vs semantic), [[adr-011]]

## Context

Wave J research (#8) — "jump to function tokenize", "go to line 240" → resolve a (phonetically
fuzzy) spoken target to an editor motion (search, `:line`, or LSP symbol jump). No camera (unlike
Gaze-Routed) and no blind grid (unlike Voice Mouse Grid) — semantic targets. Fills a real gap:
YazSes has no voice *navigation*. Anchors: Cursorless (canonical structural voice-coding system,
github.com/cursorless-dev), Nowrin & Vertanen "Programming by Voice," ACM CUI 2023 (DOI
10.1145/3571884.3597130).

## Decision

Add an opt-in **Voice Jump-to-Symbol**: `[jump] enabled=false`. Pure cores: `resolve_target(text)`
→ a `Target(kind, value)` for line / symbol / search intents, `fuzzy_pick(name, symbols)` (difflib
close-match against a provided symbol list), and `plan_motion(target, symbols)` → a `Motion(kind,
payload)` (`goto_line` / `goto_symbol` / `search`, with a search fallback when no symbol matches).
Dependency-free (stdlib `difflib`). The live symbol list from the existing `NeovimBridge`/LSP is
deferred. OFF by default.

## Consequences

- Semantic voice navigation; pure resolve + fuzzy + plan, testable with a symbol list.
- Distinct from Voice Pilot (UI), Mouse Grid (pixels), Gaze (camera).
- Privacy (ADR-011): local string matching; symbols over the existing local LSP bridge.
- Caveat: with no symbol list it falls back to search → the LSP symbol feed is the deferred tier;
  off by default.
