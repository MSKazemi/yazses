# ADR-v2-085 — Chorded Shortcut Synthesis

**Status:** Accepted (2026-07-02) · Wave K
**Context links:** [[adr-v2-055-emoji-symbol-by-voice]], [[project_cli_usability]] (macros are predefined), [[adr-011]]

## Context

Wave K research (#1) — parse an *arbitrary* spoken modifier+key chord on the fly ("press control
shift P", "escape twice", "hit F5") and inject it as a real keystroke combo — not a pre-registered
macro. Handles ctrl/alt/shift/super × any key/function-key, repeats, and named keys. Distinct from
Macros (user-predefined bindings) and the fixed built-in keystroke verbs — this synthesizes any
chord from free grammar with no prior registration, the missing "keyboard-shortcut layer." The
biggest motor-accessibility win. Anchor: Apple Vocal Shortcuts (iOS 18, on-device), Talon chords,
Apple Voice Control custom commands.

## Decision

Add an opt-in **Chorded Shortcut Synthesis**: `[chords] enabled=false`. Pure cores:
`parse_chord(text)` → a list of `KeyChord(mods, key)` (strips a leading verb, resolves modifier
words, named keys, F-keys and single chars, and a trailing repeat count → repeated chords), and
`render_chord(chord)` → the `ctrl+shift+p` form the existing `inject_key_sequence` consumes.
Dependency-free — no new backend, it reuses the injector. OFF by default.

## Consequences

- Any keyboard shortcut by voice with no pre-registration; a major hands-free/motor win.
- Pure string→keycode mapping, fully testable; reuses `inject_key_sequence`.
- Distinct from Macros (predefined) and fixed keystroke verbs.
- Privacy (ADR-011): no model; local injection only.
- Caveat: covers the common modifier/key vocabulary → exotic keysyms fall through to `None`; off
  by default.
