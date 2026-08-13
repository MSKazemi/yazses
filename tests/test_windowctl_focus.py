"""Focus a window by name, spoken (#39). Backend mocked; no desktop needed."""

from __future__ import annotations

import pytest

from yazses.windowctl.focus import (
    WindowRef,
    XdotoolWindows,
    build_window_backend,
    focus_by_name,
    match_window,
    parse_focus_command,
    wayland_limitation,
)

WINDOWS = [
    WindowRef("1", "Mozilla Firefox — YazSes docs"),
    WindowRef("2", "notes.txt — gedit"),
    WindowRef("3", "mohsen@laptop: ~/scratch/repos/yazses"),
]


class FakeBackend:
    def __init__(self, windows=WINDOWS, focusable=True):
        self._windows, self._focusable = windows, focusable
        self.focused: list[str] = []

    def list_windows(self):
        return list(self._windows)

    def focus(self, window_id):
        self.focused.append(window_id)
        return self._focusable


# ---- grammar ---------------------------------------------------------------


@pytest.mark.parametrize(("said", "target"), [
    ("focus firefox", "firefox"),
    ("focus the browser", "browser"),
    ("switch to gedit", "gedit"),
    ("go to terminal", "terminal"),
    ("activate firefox window", "firefox"),
    ("bring up my notes", "notes"),
])
def test_focus_commands_parse(said, target):
    assert parse_focus_command(said) == target


@pytest.mark.parametrize("said", [
    "i need to focus on the browser today",
    "let me switch to something else entirely and keep talking",
    "focus",
    "",
])
def test_ordinary_speech_is_not_a_focus_command(said):
    """Anchored at both ends: 'focus' is an ordinary word."""
    assert parse_focus_command(said) is None


# ---- matching --------------------------------------------------------------


def test_matches_on_a_word_from_the_title():
    assert match_window("firefox", WINDOWS).id == "1"


def test_matches_case_insensitively():
    assert match_window("FIREFOX", WINDOWS).id == "1"


def test_no_match_returns_none():
    assert match_window("photoshop", WINDOWS) is None


def test_empty_inputs_are_safe():
    assert match_window("", WINDOWS) is None
    assert match_window("firefox", []) is None


def test_ambiguous_query_refuses_rather_than_guessing():
    """Two near-identical titles: picking one sends dictation somewhere random."""
    ambiguous = [
        WindowRef("1", "notes.txt — gedit"),
        WindowRef("2", "notes.md — gedit"),
    ]
    assert match_window("notes gedit", ambiguous) is None


def test_two_windows_with_the_same_title_refuse():
    same = [WindowRef("1", "Untitled Document"), WindowRef("2", "Untitled Document")]
    assert match_window("untitled document", same) is None


# ---- focusing --------------------------------------------------------------


def test_focus_calls_the_backend_once_with_the_matched_id():
    backend = FakeBackend()
    assert focus_by_name("firefox", backend).id == "1"
    assert backend.focused == ["1"]


def test_no_backend_focuses_nothing():
    assert focus_by_name("firefox", None) is None


def test_unmatched_query_focuses_nothing():
    backend = FakeBackend()
    assert focus_by_name("photoshop", backend) is None
    assert backend.focused == []


def test_backend_failure_is_reported_as_no_focus():
    backend = FakeBackend(focusable=False)
    assert focus_by_name("firefox", backend) is None


# ---- the X11 backend, with the CLI mocked ----------------------------------


def test_xdotool_backend_lists_windows_with_titles():
    calls = []

    def runner(argv):
        calls.append(argv)
        if argv[1] == "search":
            return "11\n22\n"
        return {"11": "Mozilla Firefox\n", "22": "notes.txt — gedit\n"}[argv[2]]

    windows = XdotoolWindows(runner=runner).list_windows()
    assert [w.id for w in windows] == ["11", "22"]
    assert windows[0].title == "Mozilla Firefox"


def test_xdotool_backend_skips_windows_with_no_title():
    def runner(argv):
        if argv[1] == "search":
            return "11\n22\n"
        return "Firefox\n" if argv[2] == "11" else "\n"

    assert [w.id for w in XdotoolWindows(runner=runner).list_windows()] == ["11"]


def test_xdotool_failure_yields_no_windows_rather_than_raising():
    def runner(argv):
        raise OSError("xdotool exploded")

    assert XdotoolWindows(runner=runner).list_windows() == []


def test_xdotool_focus_reports_failure_instead_of_raising():
    def runner(argv):
        raise OSError("no such window")

    assert XdotoolWindows(runner=runner).focus("11") is False


# ---- honest unavailability -------------------------------------------------


def test_wayland_has_no_backend():
    """Wayland forbids cross-client focus; offering it would be a lie."""
    assert build_window_backend("wayland") is None


def test_the_wayland_message_says_why_and_what_still_works():
    message = wayland_limitation()
    assert "Wayland" in message
    assert "X11" in message
    assert "compositor" in message, "must point at the thing that still works"
