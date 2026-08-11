# ADR-v2-094 — Focus-Class Auto-Profile Switching

**Status:** Accepted (2026-07-02) · Wave K
**Context links:** [[adr-v2-057-focus-aware-mode]] (per-app modes), profiles.py (per-editor grammar), [[adr-011]]

## Context

Wave K research (#2) — auto-select the dictation grammar profile from the *class* of the focused
window (terminal → shell keystrokes, editor → code mode, browser/office → prose) so the user never
manually switches profiles as they move between apps. YazSes already has per-editor `profiles.py`
and Focus-Aware Mode (per-app *cleanup*); this adds a coarse **class** layer above exact app
matching, with a sensible default per class so *any* terminal/editor/browser works out of the box.
Anchor: context-aware input / activity-recognition line of research.

## Decision

Add an opt-in **Focus-Class Auto-Profile**: `[focusprofile] enabled=false`. Pure cores:
`classify_focus(app_class)` → a coarse class (terminal/editor/browser/chat/office/unknown) from
keyword sets, and `resolve_profile(window_title, app_class, rules)` → a profile name — user `rules`
(substring → profile) win, else a per-class default (`terminal→shell`, `editor→code`,
`browser→prose`, …), else `None`. Dependency-free; the OS window-title comes from the existing
platform layer. OFF by default.

## Consequences

- Zero-touch profile switching across apps; any terminal/editor/browser works without config.
- Pure classifier + resolver → fully testable; reuses the platform focus query.
- Layers above exact per-app matching (rules override the class default).
- Privacy (ADR-011): reads only the focused window's class/title locally; nothing stored or sent.
- Caveat: coarse keyword classification (unknown → None → no switch); off by default.
