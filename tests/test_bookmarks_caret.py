"""Session bookmarks resolve a real caret, never a keypress count (#162).

The acceptance criteria on the issue, made executable. Pure: no desktop, no
AT-SPI, no injector — the backend is a fake, which is the point of the seam.
"""

from __future__ import annotations

import pytest

from yazses.bookmarks.caret import Caret, Refusal, capture, jump, resolve_jump
from yazses.bookmarks.store import BookmarkStore, parse_bookmark_command


class FakeCaret:
    """A caret backend that records moves instead of touching a desktop."""

    def __init__(self, caret: Caret | None, *, movable: bool = True):
        self._caret = caret
        self._movable = movable
        self.moves: list[Caret] = []

    def caret(self):
        return self._caret

    def move_to(self, caret):
        self.moves.append(caret)
        if self._movable:
            self._caret = caret
        return self._movable


DOC = "gedit:notes.txt"


# ---- capturing -------------------------------------------------------------


def test_capture_reads_the_backend_caret():
    assert capture(FakeCaret(Caret(DOC, 120))) == Caret(DOC, 120)


def test_capture_without_a_backend_refuses():
    assert capture(None) is Refusal.NO_BACKEND


def test_capture_refuses_when_nothing_reports_a_caret():
    """A canvas or a terminal drawing its own cursor has no AT-SPI caret."""
    assert capture(FakeCaret(None)) is Refusal.NO_CARET


# ---- the acceptance criteria ----------------------------------------------


def test_jump_is_a_single_positioning_call():
    """Never N keypresses: that was the unbounded-injection flaw in #160."""
    backend = FakeCaret(Caret(DOC, 4000))
    saved = Caret(DOC, 12)

    assert jump(saved, backend) == saved
    assert backend.moves == [saved], "exactly one move, regardless of distance"


def test_caret_moved_externally_between_set_and_jump_still_lands_right():
    """The core failure of the counting model.

    The user sets a bookmark, then clicks the mouse somewhere else, types, and
    jumps back. An offset counted from what we injected would be meaningless by
    now; an absolute position is not.
    """
    backend = FakeCaret(Caret(DOC, 50))
    saved = capture(backend)
    assert isinstance(saved, Caret)

    backend._caret = Caret(DOC, 3175)          # mouse click + a lot of typing

    assert jump(saved, backend) == Caret(DOC, 50)
    assert backend.caret() == Caret(DOC, 50)


def test_no_backend_refuses_rather_than_guessing():
    assert jump(Caret(DOC, 10), None) is Refusal.NO_BACKEND


def test_jump_to_an_unknown_bookmark_refuses():
    assert jump(None, FakeCaret(Caret(DOC, 10))) is Refusal.UNKNOWN_BOOKMARK


def test_jump_into_a_different_document_refuses():
    """A jump that lands in another file would drop the next dictation there."""
    backend = FakeCaret(Caret("firefox:some page", 10))
    assert jump(Caret(DOC, 400), backend) is Refusal.DIFFERENT_DOCUMENT
    assert backend.moves == [], "must not move the caret in the wrong document"


def test_backend_refusing_the_move_is_reported():
    backend = FakeCaret(Caret(DOC, 10), movable=False)
    assert jump(Caret(DOC, 400), backend) is Refusal.MOVE_FAILED


def test_resolve_does_not_move_anything():
    """The policy is separable from the effect, so it can be tested and reused."""
    backend = FakeCaret(Caret(DOC, 10))
    assert resolve_jump(Caret(DOC, 400), backend) == Caret(DOC, 400)
    assert backend.moves == []


# ---- store integration -----------------------------------------------------


def test_a_bookmark_round_trips_through_the_store():
    store, backend = BookmarkStore(), FakeCaret(Caret(DOC, 88))
    store.add("intro", capture(backend))
    backend._caret = Caret(DOC, 900)
    assert jump(store.goto("intro"), backend) == Caret(DOC, 88)


def test_goto_missing_name_is_a_refusal_not_a_crash():
    assert jump(BookmarkStore().goto("nope"), FakeCaret(Caret(DOC, 1))) is Refusal.UNKNOWN_BOOKMARK


# ---- grammar anchoring -----------------------------------------------------
#
# "bookmark" is an ordinary English word. The pattern was anchored only at the
# end, so any sentence ending in it was swallowed as a command.


@pytest.mark.parametrize("said", [
    "click bookmark",
    "the bookmark",
    "open the bookmark",
    "i added a bookmark",
    "delete that bookmark",
])
def test_ordinary_speech_containing_bookmark_is_typed_not_executed(said):
    assert parse_bookmark_command(said) is None, f"{said!r} must be dictated, not executed"


@pytest.mark.parametrize(("said", "expected"), [
    ("bookmark", ("add", None)),
    ("bookmark this", ("add", None)),
    ("bookmark here", ("add", None)),
    ("bookmark as intro", ("add", "intro")),
    ("bookmark called intro", ("add", "intro")),
    ("jump to bookmark", ("goto", None)),
    ("go to bookmark intro", ("goto", "intro")),
    ("jump to my last bookmark", ("goto", None)),
])
def test_real_bookmark_commands_still_parse(said, expected):
    assert parse_bookmark_command(said) == expected


# ---- honesty ---------------------------------------------------------------


def test_bookmarks_stays_unwired_until_a_runtime_path_reads_it():
    """The registry's honesty rule: a slug leaves _UNWIRED only when reachable.

    The caret seam exists now, but nothing in the daemon calls it yet, so
    `features enable bookmarks` must still refuse. Deleting this test is the
    correct thing to do in the PR that wires it — not before.
    """
    from yazses.system.features import _UNWIRED

    assert "bookmarks" in _UNWIRED
