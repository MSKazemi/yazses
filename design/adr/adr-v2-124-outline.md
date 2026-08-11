# ADR-v2-124 — Spoken Outline (voice-driven outline structuring)

**Status:** Accepted (2026-07-03) · Wave N
**Context links:** reflow (dictation reflow), markup (structured markup), srscap, [[adr-011]]

## Context

Wave N research (#10) — dictation lands as flat prose, but idea capture (notes, planning, ADHD
workflows) wants *structure*: nested items you can indent, promote, and collapse as you speak. The
set has Reflow (post-hoc restructuring) and Markup (inline rendering), but no live outline model
driven by spoken structural verbs. Anchor: OPML and classic outliner verbs (new item / indent /
promote / collapse); ADHD idea-capture research.

## Decision

Add an opt-in **Spoken Outline**: `[outline] enabled=false, format="markdown"`. Pure core in
`outline/tree.py`: an outline is a flat list of `OutlineItem(text, level, collapsed)` plus a
cursor; `apply_outline_op(state, op, text)` applies `add / indent / promote / collapse / expand /
up / down` and returns a NEW state (indent capped at previous-item level + 1, promote floored at
0, unknown ops are no-ops); `render(state, fmt)` emits Markdown bullets (collapsed subtrees
hidden) or nested OPML (escaped, full tree). OFF by default.

## Consequences

- Structured, hands-free idea capture; the outline state machine is trivially undoable.
- Pure functional ops + renderer → fully testable, no dependency.
- Distinct from Reflow (batch, post-hoc) — this is live, verb-driven structure.
- Privacy (ADR-011): local text only.
- Caveat: rendering targets Markdown/OPML text injection; live editor tree-views are a later
  bridge concern; off by default.
