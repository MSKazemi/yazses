# ADR-v2-070 — Voice-Controlled Window / Workspace Management

**Status:** Accepted (2026-07-02) · Wave I
**Context links:** [[adr-v2-028-voice-mouse-grid]] (moves cursor vs windows), [[adr-v2-037-atspi-voice-pilot]] (in-app UI vs WM), [[adr-011]]

## Context

Wave I research (#8) — hands-free desktop layout: "move window left half", "workspace 3",
"maximize", "tile top left". A grammar maps spoken layout commands to window-manager actions via
`wmctrl`/`hyprctl`/`swaymsg` (Linux), AppleScript (macOS), or Win32 (Windows). Distinct from Voice
Mouse Grid (moves the *cursor*), AT-SPI Voice Pilot (targets *in-app UI elements*), and Head-
Pointer (pointing) — window/workspace layout control is untouched. A real motor-accessibility win.

## Decision

Add an opt-in **Voice Window Management**: `[windowctl] enabled=false`. The pure core
`parse_wm_command(text)` returns a `WmAction(kind, arg)` for snap (halves + quarters), maximize,
minimize, fullscreen, center, close-window, absolute `workspace N`, and relative next/previous
workspace. Dependency-free. Per-compositor backends (wmctrl/hyprctl/swaymsg/AppleScript/Win32)
that execute the action are deferred behind a `windowctl` extra. OFF by default.

## Consequences

- Layout control by voice — impossible in a cloud tool (needs local WM access).
- Pure grammar → fully testable without a live desktop.
- Distinct from Mouse Grid / Pilot / Head-Pointer.
- Privacy (ADR-011): parsing is local; backends use OS WM IPC, no network.
- Caveat: the executing backend is per-compositor and deferred; the grammar is off by default.
