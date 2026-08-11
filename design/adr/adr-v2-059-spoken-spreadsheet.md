# ADR-v2-059 — Spoken Spreadsheet / Table Mode

**Status:** Accepted (2026-07-02) · Wave H
**Context links:** [[adr-v2-047-field-aware-dictation]] (form field vs 2D cell), commands/grammar, [[adr-011]]

## Context

Wave H research (#1) — cell-addressed dictation + grid navigation for any spreadsheet or table,
hands-free: "A1 revenue, tab, forty-two hundred, down, next row" emits cell text + Tab/Enter/arrow
keystrokes; "go to B7". Anchors: intelligent voice-navigation of spreadsheets (arXiv 0809.3571),
Windows Voice Access 2025 natural-command upgrades.

Distinct from Field-Aware Dictation (targets *form fields*) — this is 2D cell addressing + grid
traversal, which no mainstream offline dictation tool does.

## Decision

Add an opt-in **Spoken Spreadsheet**: `[spreadsheet] enabled=false`. Two pure cores:
`parse_grid_move(text)` maps a spoken movement phrase to a key sequence (next row → Return, next
cell → Tab, cell up/down/left/right, start/end of row, top/bottom of column), and
`parse_cell_reference(text)` parses a spoken cell address ("B7", "column B row 7") into a
normalized reference. Both dependency-free, extending the existing commands/grammar → dispatch →
injector path (dispatch wiring deferred). OFF by default.

## Consequences

- First spatial/2D table-entry capability; pure keystroke logic, no model.
- Distinct from Field-Aware (2D cells vs form fields).
- Privacy (ADR-011): pure local keystroke injection; impossible in cloud tools (can't drive
  arbitrary local apps).
- Caveat: cell-address parsing can false-match word+number tokens → gated to command mode + off
  by default.
