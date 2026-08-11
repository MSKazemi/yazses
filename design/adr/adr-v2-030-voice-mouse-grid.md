# ADR-v2-030 — Voice Mouse Grid (pointer control by voice)

**Status:** Accepted (2026-07-02) · Wave E
**Context links:** [[adr-v2-007-atspi-pilot]] (needs a11y tree), [[adr-v2-003-gaze-routed]] (targets windows), [[adr-011]]

## Context

The Wave E research (#10) proposes Talon-style hands-free pointer control: an overlaid grid
lets you drive the cursor and click by voice ("three… seven… click") when no accessibility
tree is available. AT-SPI Voice Pilot (ADR-v2-007) needs a *semantic* element tree (fails on
canvas/games/custom UIs); Gaze routing (ADR-v2-003) targets *windows*, not pixels. A geometric
voice grid works on *any* pixels — the universal fallback.

## Decision

Add an opt-in **voice mouse grid**: `[mousegrid] enabled=false, cols=3, rows=3`. The pure
core is grid-subdivision math — `subdivide(region, cell, cols, rows)` returns the sub-rectangle
for a numbered cell, and `resolve_point(region, path, cols, rows)` applies a sequence of cell
selections (recursive coarse-to-fine) and returns the center point to click. Reuses the
existing overlay (`yazses-overlay`, PySide6) to draw the grid and the existing injector to move/
click. No ML. OFF by default.

## Consequences

- Universal pixel-level fallback where AT-SPI Pilot and Gaze can't resolve a target.
- Pure geometry → fully testable; rendering + click reuse existing components.
- On-device only (ADR-011); pure geometry + local injection, no capture, no model.
- Caveat: multi-step selection is slower than a direct a11y click → prefer Pilot when a tree
  exists; the grid is the fallback. Off by default.
