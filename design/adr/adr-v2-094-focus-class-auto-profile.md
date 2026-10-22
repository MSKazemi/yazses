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

## Implementation note (2026-10-23)

The decision above is unchanged; this records what was built, because two statements in it no
longer describe the code.

**`commands/profiles.py` is per-editor keymaps, not a per-editor grammar.** The Context and the
context links call it "per-editor grammar". Since commit e9df4057 (2026-10-22) it is a table of
key overrides on the dispatcher's VS Code-style keymap (`commands/dispatch.py::DEFAULT_KEYMAP`).
The grammar (`commands/grammar.py`) still decides *what* was asked, and is the same in every
application. The profile only decides *which keys* carry it out. Built-in profiles are `default`,
`vscode`, `jetbrains` and `sublime`. An override of `None` refuses the action: nothing is sent and
nothing is typed, rather than a guessed key. It sits behind `[commands] editor_profiles` (off by
default); `[commands] profile = "auto"` follows the focused application, and a profile name pins
it. The focused application is read when the command is dispatched, through the text-target
guard's detector (AT-SPI, or `xdotool` on X11). With no source (macOS, Windows, a Wayland session
without AT-SPI) the default keys are used and the reason is logged once. User-facing description:
[Voice commands → Per-application behaviour](../../docs/use-cases/voice-commands.md).

**The two layers are independent.** Editor profiles match the application class themselves
(`profiles.match_app`). They do not consume this ADR's `classify_focus` class, and
`[focusprofile]` does not choose an editor profile.

**What `[focusprofile]` does as wired.** It does not switch grammar or keystrokes. In
`core/daemon.py`, when `[focusprofile] enabled` is on, the focused window's class is classified,
and a `shell` or `code` result sets the post-processing tone to `verbatim`, so cleanup does not
reformat a command line or code. It does this only when no user-written `[profiles.<app>]` glob
already set a tone. `prose` changes nothing, because prose is what the default already does.
Two parts of the decision are not wired. The window-title argument and the user `rules` exist in
`focusprofile/resolve.py::resolve_profile`, but the daemon passes neither, and `[focusprofile]`
has no `rules` key.
