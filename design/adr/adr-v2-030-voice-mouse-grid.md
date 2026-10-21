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

## Implementation (2026-10-21, WIRE-MOUSEGRID-001)

- `mousegrid/grammar.py` (pure): whole-utterance, anchored phrases — "mouse grid" opens; while
  open, cell numbers (words up to sixteen, or digits), `click` / `right click` / `double click`,
  `back`, `cancel`. Kept out of the always-on `commands/grammars/en.py` so no user who has not
  enabled the section has "click" claimed.
- `mousegrid/session.py` (pure): the zoom state machine, a 30 s idle close, no click before a
  cell is chosen, no zoom below a pixel.
- `mousegrid/runtime.py`: the daemon's consumer. Built only when `[mousegrid] enabled`; the
  `PointerSink` is built on the first pointer action and must offer absolute motion (X11,
  macOS) — relative-only backends are refused with a reason. Honours the hands-free pause. An
  open grid hands back any utterance that is not a grid command, closing itself.
- Overlay: `overlay/grid.py` (pure parse + poller over the `mousegrid` IPC method) and
  `overlay/grid_widget.py` (click-through Qt window), both loaded only when the section is on.
- Thresholds (timeout, vocabulary) are tuned on synthetic transcripts only.

## Consequences

- Universal pixel-level fallback where AT-SPI Pilot and Gaze can't resolve a target.
- Pure geometry → fully testable; rendering + click reuse existing components.
- On-device only (ADR-011); pure geometry + local injection, no capture, no model.
- Caveat: multi-step selection is slower than a direct a11y click → prefer Pilot when a tree
  exists; the grid is the fallback. Off by default.
