# Desktop window — the violet app design

Status: **IMPLEMENTED** on branch `feat/desktop-app-ui` (2026-11-26), unmerged and
unreleased. §8 says where the build departed from this document.
Builds on [the settings-window redesign](2026-10-24-settings-window-redesign.md).

## 1. Intent

The settings window configures YazSes but cannot show whether dictation works, run a
meeting, or transcribe a file; those need a terminal. The approved mockup (a dark violet
window with a sidebar) turns the same window into the place a desktop user does those
jobs. "Done" means every sidebar page works against the real product: no control that
does nothing, no invented figure.

## 2. Goals

- Nine sidebar entries from the mockup, plus the existing Audio, General, Hands-free and
  Updates pages, which keep their keys, widgets and behaviour.
- Each problem the daemon reports is shown with one clear next step.
- Capability toggles on the new pages are the *same* staged switches as on Features.
- Dark violet and light violet themes, and "match my desktop"; WCAG AA text contrast.
- Everything the pages decide is in Qt-free modules with direct unit tests.

## 3. Non-goals

- No new IPC method. The pages use `status`, `meeting_start`, `meeting_stop`,
  `meeting_status` and `recalibrate_mic`, which exist.
- No new CLI command or flag. File transcription runs `yazses transcribe`.
- No new network path, dependency, or stored copy of what the user said. No dictation
  history; the file list lasts for the window's lifetime.
- No daemon behaviour change.
- Not built: multi-step macro builder, meeting pause, system-audio capture, benchmarks.

## 4. Approaches

| Approach | Trade-off |
|---|---|
| **A. Extend the settings window with new pages** (chosen) | Reuses staging, Apply, restart, dependency install and theme plumbing; one window. The sidebar is longer than the mockup's. |
| B. A second "app" window with its own command | Matches the mockup exactly, but duplicates Apply logic and adds a CLI surface. |
| C. A web front end | New runtime and a local server: against the offline-first, small-dependency rules. |

## 5. Design

### 5.1 Pages

Sidebar order: Overview, Dictation, Meetings, File transcription, Voice commands,
Features, Accessibility, Models, Audio, General, Hands-free, Updates. The window opens on
Overview. `Models` is the existing `speech` page, relabelled; its key is unchanged.

| Page | Content | Source of truth |
|---|---|---|
| Overview | Health state with one fix, hold-to-talk key, system check, links to jobs | `status` poll |
| Dictation | Key, live level, practice box with word count, writing-option switches | `status`; feature switches |
| Meetings | Enable, start/stop, live draft, stored meetings, transcript, rename speakers, export | `meeting_*`; `meeting/store.py` |
| File transcription | Choose or drop a file, format, model, speakers; run/cancel; preview; session list | `yazses transcribe` subprocess |
| Voice commands | Searchable example phrases, command-feature switches | the real command grammar |
| Accessibility | A card per accessibility capability | feature registry |
| General (added) | Appearance, and "what can leave this computer" facts | config |

### 5.2 Switches on the new pages

A card holds a switch that mirrors the Features checkbox for its slug. Toggling it calls
`setChecked` on that checkbox, so experimental confirmation, staging, dirty marks, Apply
and dependency install behave identically. Every staged change refreshes all mirrors.

### 5.3 Threads

No page blocks the GUI thread on IPC or disk of unbounded size. Status and meeting calls
run on a background thread and hand results back through a Qt signal. A poll is skipped
while the previous one is in flight, and runs only while its page is visible. File
transcription is a `QProcess`, so Cancel kills it; closing the window while one runs asks
first.

### 5.4 Theme

`[window] theme` = `violet-dark` (default) | `violet-light` | `system`. An unknown value
behaves as the default. The palette is data in a pure module whose contrast a test
checks. `system` applies no palette or stylesheet, leaving today's look. The theme
previews immediately and is saved by Apply.

The default changes the look of an existing install. It is the approved design; it is a
repaint of an optional window, not a capability, and `system` restores the previous look.

### 5.5 Privacy panel

Facts read from config, never switches: AI cleanup (on/off, and whether a non-local
endpoint is allowed), remote dictation, learning corpus, meeting audio retention. A
button opens the data folder.

## 6. Constraints

AGENTS.md: PySide6 imported lazily; pure logic beside a Qt shell; tests in the same
change; test files named `tests/test_settingsui_*.py` so the GUI CI job runs them;
generated docs regenerated; `CHANGELOG.md` updated; no AI authorship credit.

## 7. Testing

- Pure modules tested without Qt.
- Offscreen Qt tests per page, with IPC, subprocess and dialogs injected.
- Real-window screenshots in both themes before completion.
- Gates: `pytest`, `ruff check src tests scripts`, `mypy src` with the `desktop` extra.

## 8. As built

- **Dark violet is the default**, decided by the owner on 2026-11-26. It changes how an
  existing install looks; **General → Window look → Match my desktop** restores it.
- **Overview has a third fix, Restart**, for a daemon in `error`.
- **"Slow" is not "absent".** A daemon that is alive but misses the 2 s IPC wait is shown
  as busy, with no Start button. `meeting_start`/`meeting_stop` wait 60 s.
- **Start runs `yazses start --no-autostart`**, and does nothing to a running daemon:
  the CLI would restart it, and a button must not also add a login item.
- **The window stays open** while a start or restart begun on a page is running.
- **Speaker labels for files** are offered only when the diarization libraries are
  present; otherwise the page shows the Recording Import switch that installs them.
- **A successful transcription's `Note:` lines are shown** above the result.
- **Drawn, not shipped:** the brand mark, sidebar icons and the check box on the violet
  themes (Fusion's unchecked box was invisible on the dark window).
- **Five existing tests changed:** three to the new page order and the Models label
  (`test_settingsui_pages.py`, `_window_pages.py`, `_window_polish.py`), and two guards
  to map the new theme setting (`test_report_classifies_every_config_string.py`,
  `test_reset_scope_names_every_value_row.py`).
- **Verified on Linux:** the daemon's own status and meeting handlers over a real
  socket (microphone and model stood in), an installed wheel, and a Wayland desktop.
- **Not verified:** the window on macOS, a frozen build, a screen-reader listening test,
  or live dictation and recording with a microphone.
