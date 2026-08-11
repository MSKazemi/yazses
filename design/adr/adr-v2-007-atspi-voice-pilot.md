# ADR-v2-007 — AT-SPI Voice Pilot (accessibility-tree desktop control)

**Status:** Accepted (2026-07-02) · Wave B
**Context links:** [[adr-v2-000-interaction-layer]], [[adr-v2-004-context-primed-dictation]] (context/LSP), [[adr-011]] (offline/no-capture)

## Context

Computer-use agents lean on screenshots + cloud vision, yet the research
(internal) finds accessibility-tree control (AT-SPI
on Linux, UI Automation on Windows, AX on macOS) is superior for local agents — exact
element IDs, millisecond actions, and **nothing rendered or screenshotted** — but is
barely shipped, especially on Linux where YazSes already runs.

## Decision

Add an opt-in **AT-SPI Voice Pilot**: commands like "click Save", "focus the terminal",
"check the third box" are resolved against the live accessibility tree of the focused
window and actioned directly (no vision, no screenshots).
- Linux-first via `pyatspi` (GNOME/KDE); protocol-shaped so UIA/AX can follow.
- Fuzzy match spoken label → tree element; ambiguity resolved by an ordinal ("third") or a
  confirm; actions limited to activate/focus/toggle/set-value.
- Graceful fallback: apps with broken/absent trees (some Electron, terminals) degrade to
  the existing keystroke command grammar.

Config: `[pilot] enabled=false`, `backend=atspi|none`, `match_threshold`, `confirm_ambiguous`.
New package `pilot/` (tree query + label match + action); reuses command grammar + confirm.

## Consequences

- **+** Maximally private (no screenshots), ms latency, Linux-first moat; huge for motor accessibility.
- **+** Extends existing window/context awareness; degrades to keystrokes we already ship.
- **−** Accessibility trees are incomplete in some toolkits → detect + fall back; never assume.
- **−** Wayland restricts cross-window control → document per-compositor behavior; optional dep
  (pyatspi) behind an extra; default off.
