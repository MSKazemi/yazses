"""Which pages the settings window has, and the small decisions its navigation makes. Pure.

The window is a sidebar of pages with the capability list on one of them. Everything the
sidebar and the Features page's category list have to *decide* — what a page is called,
which pages hold unsaved changes, which categories can be picked under a filter, what each
category's count says — is here, with no Qt and no I/O, so it is tested directly
(the house split: ``search.py`` and ``controller.py`` are pure beside the Qt shell in
``app.py``). The shell only paints what these functions answer.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from yazses.settingsui.search import matches


@dataclass(frozen=True)
class PageSpec:
    """One sidebar entry and the heading of the page it opens."""

    key: str
    label: str
    title: str
    blurb: str


PAGES: tuple[PageSpec, ...] = (
    PageSpec(
        "general", "General", "General",
        "The key you hold to dictate, and how changes here are saved.",
    ),
    PageSpec(
        "speech", "Speech", "Speech",
        "Which model hears you, in what language, and how the text reaches your window.",
    ),
    PageSpec(
        "audio", "Audio", "Audio",
        "Your microphone, and the level below which audio counts as silence.",
    ),
    PageSpec(
        "features", "Features", "Features",
        "Turn capabilities on or off. Hover a row, or click ? for details and examples.",
    ),
    PageSpec(
        "handsfree", "Hands-free", "Hands-free",
        "Pause, resume and recover the camera-driven hands-free inputs.",
    ),
    PageSpec(
        "updates", "Updates", "About and updates",
        "Check for a newer version and finish installing libraries for features you turned on.",
    ),
)

#: Appended to a sidebar label while its page holds changes that Apply has not written.
DIRTY_MARK = " •"

#: Which page each form control belongs to, keyed by the window's *baseline attribute* for
#: that control: the value it had when last saved, which is exactly what "has it changed"
#: compares against. Keyed by that name rather than by widget so a control added without a
#: baseline cannot be saved either — and ``test_settingsui_window_pages`` fails if the
#: window grows a baseline this map does not know, which is how a hand-written set stays
#: honest. Features is absent on purpose: it is dirty because capabilities are staged.
FIELD_PAGES: dict[str, str] = {
    "_hotkey_baseline": "general",
    "_profile_baseline": "speech",
    "_model_baseline": "speech",
    "_language_baseline": "speech",
    "_compute_baseline": "speech",
    "_prompt_baseline": "speech",
    "_backend_baseline": "speech",
    "_consent_baseline": "speech",
    "_guard_baseline": "speech",
    "_padding_baseline": "speech",
    "_mic_baseline": "audio",
    "_vad_baseline_pos": "audio",
}


def page_label(label: str, *, dirty: bool) -> str:
    """The sidebar text for a page: its name, plus a marker while it has unsaved changes."""
    return f"{label}{DIRTY_MARK}" if dirty else label


def dirty_page_keys(*, staged_features: int, changed_fields: Iterable[str]) -> frozenset[str]:
    """The pages holding changes Apply has not yet written.

    An unknown field name is ignored, not raised: this runs on every edit and must never
    turn a keystroke into a traceback; the completeness test is what notices the gap.
    """
    keys = {FIELD_PAGES[name] for name in changed_fields if name in FIELD_PAGES}
    if staged_features > 0:
        keys.add("features")
    return frozenset(keys)


@dataclass(frozen=True)
class CategoryEntry:
    """One line of the Features page's category list."""

    category: str
    enabled: int
    total: int
    matching: int


def category_entries(
    groups: Sequence, enabled_of: Callable[[str], bool], query: str
) -> tuple[CategoryEntry, ...]:
    """Per-category counts for the category list: on, total, and matching *query*.

    *enabled_of* answers for a slug what the window currently shows (staged state
    included), so the counts move the moment a box is ticked rather than after Apply.
    """
    entries = []
    for group in groups:
        on = sum(1 for row in group.rows if enabled_of(row.slug))
        hits = sum(1 for row in group.rows if matches(row, query, category=group.category))
        entries.append(CategoryEntry(group.category, on, len(group.rows), hits))
    return tuple(entries)


def category_item_text(entry: CategoryEntry, *, filtering: bool) -> str:
    """The list line: ``Name · on/total``, or ``Name · N match`` while a filter is active."""
    if filtering:
        return f"{entry.category} · {entry.matching} match"
    return f"{entry.category} · {entry.enabled}/{entry.total}"


def category_selectable(entry: CategoryEntry, *, filtering: bool) -> bool:
    """A category the filter has emptied cannot be picked: it would show a blank pane."""
    return not filtering or entry.matching > 0


def section_visible(category: str, *, selected: str | None, matching: int) -> bool:
    """Whether a category's section shows: it is selected (or All) and the filter left rows."""
    if matching <= 0:
        return False
    return selected is None or selected == category


def effective_selection(
    selected: str | None, entries: Sequence[CategoryEntry], *, filtering: bool
) -> str | None:
    """The category to show, given a filter that may have emptied the chosen one.

    ``None`` is the "All" entry. A filter that leaves the chosen category with nothing
    falls back to All instead of leaving a blank pane under a selected row, and a category
    that is no longer in the model is treated the same way.
    """
    if selected is None:
        return None
    for entry in entries:
        if entry.category == selected:
            return selected if category_selectable(entry, filtering=filtering) else None
    return None
