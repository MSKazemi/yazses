# Settings window redesign — sidebar + pages

Status: **IMPLEMENTED** on branch `feat/settings-sidebar-pages` (2026-10-24), unmerged and
unreleased. Path: architectural. The owner delegated the open questions (§7) and the
implementation; where the build departed from this document, §9 says so.

## 1. Problem

`SettingsWindow.__init__` (`src/yazses/settingsui/app.py`) stacks everything in one
`QVBoxLayout`: tooltip hint, snap banner, Hands-free button, hotkey row, Speech group
(8 rows), Audio group, maintenance box, filter box, and only then the `QScrollArea` holding
the capability toggles (well over a hundred rows, grouped by category). The scroll area
receives whatever height is left. At the default 680x760 size that is roughly 70 px, so the
Features list — the largest part of the product — is effectively invisible, and the window
reads as an unstructured form.

## 2. Goals / success criteria

- Any setting reachable in two clicks or one search, without scrolling past unrelated controls.
- The Features list gets the full height of the window, with category navigation.
- Pending changes are always visible and Apply is always reachable.
- Follows the desktop theme (light and dark); keeps the WCAG AA muted-text guarantee of
  `settingsui/theme.py`.

## 3. Non-goals (hard constraints)

- **No behavior change.** Staging, `PendingChanges`, Apply, restart offer, dependency install,
  language-profile worker, experimental confirmation, Restore defaults semantics: untouched.
- **No config-key, CLI, or IPC change** (these are L3 interfaces per `AGENTS.md`).
- No new dependency; PySide6 stays the optional `desktop` extra, imported lazily.
- No new network access, telemetry, or anything under ADR-019.
- The `?` details dialog, tooltips, accessible names/descriptions are preserved.

## 4. Design

### 4.1 Shell

Window default 900x640, minimum 760x520. Left sidebar (`QListWidget`, icon-less text entries
so it works on every platform without bundled assets), right `QStackedWidget`.

| Sidebar entry | Content (existing builder reused) |
|---|---|
| General | hold-to-talk key (`_build_hotkey_row`), one-paragraph note on stage-then-Apply |
| Speech | `_build_speech_rows` |
| Audio | `_build_audio_rows` (level meter + silence slider get room) |
| Features | new two-pane page, §4.2 |
| Hands-free | card with a description and an "Open hands-free controls…" button → `_open_handsfree_panel` |
| Updates | `attach_maintenance(self)` |

Pinned outside the stack:
- Top: the snap-permission banner (`_add_snap_banner`), unchanged.
- Bottom footer bar: **Restore defaults** (left), live status text (centre, replaces the
  `_hint` line but `_hint` keeps its role for `_apply()`/`_busy()` callers), **Apply** (right).
- Sidebar entries carry a "•" marker when their page holds staged changes.

The long "Hover any capability…" sentence moves from the top of the window to the Features
page header, where it is relevant.

### 4.2 Features page

- Top bar: the existing filter box (same syntax: text, `on:`/`off:`, `tier:`), full width,
  with the `describe_filter` line beside it. Syntax help moves from a tooltip to a small
  popover with clickable examples.
- Left pane (~190 px): category list. "All" first, then each category as
  `Name · enabled/total`. While a filter is active, categories show their match count and
  empty ones are greyed.
- Right pane: scrolling rows for the selected category (or all, with headings, for "All").
  The category blurb becomes the pane heading.
- Rows: `_build_row` behavior unchanged (checkbox, `?`, tooltip card, accessible description).
  Visual changes only: flat rows with a divider instead of nested group boxes, a small tier
  chip from `row.tier_label`, and an accent bar on rows that are staged but not applied.
- Keyboard: Ctrl+F focuses the filter; Up/Down move through categories; sidebar entries have
  mnemonics.

### 4.3 Code shape

- New dependency-free module `settingsui/pages.py` (pure): per-category enabled/total counts,
  per-page "has staged changes", tier-chip text, category-visibility for a query. Unit-tested
  directly (house pattern: pure logic beside Qt shell, cf. `search.py`, `controller.py`).
- New Qt shell module `settingsui/shell.py`: sidebar, stack, footer. `app.py` keeps all apply /
  restart / install / language logic and only changes the layout assembly in `__init__`,
  so the 1,700-line file does not grow.
- Existing attribute names that other code and tests read (`_checkboxes`, `_info_buttons`,
  `_group_widgets`, `_filter_box`, `_filter_status`, `_hint`, `_apply_button`, `_reset_button`,
  `_hotkey_box`, `_handsfree_button`, …) are kept. Filtering continues to change *visibility
  only*; a hidden row keeps its staged state.

## 5. Testing

- Pure: `tests/test_settingsui_pages.py` for §4.3 helpers.
- Offscreen Qt smoke (same style as `tests/test_settingsui_window.py`): window builds; every
  slug has exactly one checkbox; selecting a category / filtering hides rows without
  un-staging; sidebar marker follows staged state; Apply/Restore still enabled during the
  states they were before.
- The existing `test_settingsui_*`, `test_settings_*` and `test_tray_settings_*` suites must
  pass unmodified except where a test asserts layout structure; any such edit is called out in
  the PR body.
- `tests/test_gui_job_covers_the_settingsui_family.py` must be checked: new modules need to be
  inside the family the GUI CI job covers.
- Full gates before any claim of done: `uv run python -m pytest tests/ -v`,
  `uv run ruff check src tests scripts benchmark`, `uv run mypy src` (after
  `uv sync --extra desktop`, so Qt call sites are type-checked for real).

## 6. Docs surfaces

`CHANGELOG.md` `[Unreleased]`; user-facing settings docs under `docs/` if they describe the
window layout or include screenshots; `design/architecture.md` only if the module list is
enumerated there. No generated file is touched.

## 7. Open questions for the owner

1. Sidebar order and naming — is "General" the right home for the hotkey, or should Speech own it?
2. Should the window remember its size and last-opened page between launches? (Would need a
   state file; default proposal: no, keep it stateless.)
3. Screenshots in docs: re-take after implementation, yes/no?

## 8. Risks

- Existing tests reaching into private widgets may assume the old nesting; mitigated by keeping
  attribute names and by reading those tests during planning before touching `__init__`.
- Offscreen Qt rendering differs from a real desktop; the final check must include a real
  screenshot of the window on this machine (light and dark).

## 9. As built — departures from the draft above

- **Open questions decided** (owner said to decide): the hotkey stays on General; the window is
  stateless (no remembered size or page); docs screenshots re-taken because `docs/settings-gui.md`
  already carried one.
- **Tier chips dropped.** Each row's subtitle already begins with the tier ("recommended — ..."),
  so a chip said the same thing twice. `pages.tier_chip` was removed.
- **Disabled categories are hidden, not greyed.** Greyed text was unreadable on a light theme.
- **Sidebar mnemonics became `Ctrl+1`..`Ctrl+6`.** A `QListWidget` has no mnemonics; shortcuts on
  the window work from any focus.
- **Filter syntax** is a visible line under the search box rather than a popover.
- **Page boxes are unframed** (their title is the page heading); the capability categories keep
  their titled `QGroupBox`, which the filter and the ampersand guard rely on.
- **Category list items are measured** from their wrapped text, because Qt clipped one to "…".
- New modules: `settingsui/pages.py` (pure), `settingsui/shell.py` (Qt frame). Tests:
  `test_settingsui_pages.py`, `test_settingsui_window_pages.py`. The existing window tests were
  not edited.
- **Not verified:** the look on a real desktop session. Screenshots were rendered offscreen with the
  Fusion style, in light and dark palettes.
