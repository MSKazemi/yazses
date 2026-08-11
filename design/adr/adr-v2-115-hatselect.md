# ADR-v2-115 — HatSelect (spoken structural token addressing)

**Status:** Accepted (2026-07-02) · Wave N
**Context links:** jump (cursor jump), code (spoken code), lsp_context (EditorBridge), [[adr-011]]

## Context

Wave N research (#1) — every visible token gets a tiny spoken label; you say "select alpha to
charlie", "delete bravo", "wrap alpha" to edit *structurally* without naming cursor motions. The set
has cursor Jump, Window Control, and Spoken Code awareness, but nothing that assigns stable,
collision-free per-token labels and resolves structural references against them. This is the
highest-demand hands-free voice-coding paradigm. Anchor: Cursorless (Talon plugin) decorates tokens
with colored "hats" and resolves phrases like "take funk blue" — the state of the art for hands-free
structured code editing, RSI-driven.

## Decision

Add an opt-in **HatSelect**: `[hatselect] enabled=false`. Pure cores in `hatselect/labels.py`:
`assign_labels(tokens)` → `{label: TokenRef}` using deterministic, phonetically-distinct NATO labels,
`resolve_reference(utterance, labels)` → a `Selection(start, end)` token span ("alpha to charlie" →
range), and `plan_structural_edit(verb, selection)` → a list of structural ops (select/delete/wrap/
swap) as `{op, start, end}` dicts. The labeler + resolver are pure over an already-extracted token
list; the editor bridge (fetch tokens / apply ops) reuses the existing `EditorBridge`. OFF by default.

## Consequences

- Precise hands-free structured editing for RSI/motor-impaired developers.
- Pure labeler + resolver + planner → fully testable over synthetic token lists.
- Distinct from Jump (structural span vs single cursor) and Spoken Code (edit vs dictate).
- Privacy (ADR-011): local text only.
- Caveat: needs an editor that exposes its token list (reuses `NeovimBridge`); off by default.
