"""Voice Undo/Redo Timeline (ADR-v2-089) + Session Bookmarks (ADR-v2-090) — pure cores."""
from __future__ import annotations

from yazses.bookmarks.store import BookmarkStore, parse_bookmark_command
from yazses.timeline.history import InjectionTimeline, UndoOp

# ---- undo/redo timeline ----------------------------------------------------

def test_undo_last_burst():
    tl = InjectionTimeline()
    tl.record("hello ")
    tl.record("world")
    assert tl.undo("last") == UndoOp(5, "")     # removes "world"
    assert tl.text() == "hello "


def test_undo_word_and_sentence():
    tl = InjectionTimeline()
    tl.record("one two three")
    assert tl.undo("word") == UndoOp(len(" three"), "")
    assert tl.text() == "one two"

    tl2 = InjectionTimeline()
    tl2.record("Hello world. Bye now")
    op = tl2.undo("sentence")
    assert op == UndoOp(len(" Bye now"), "")
    assert tl2.text() == "Hello world."


def test_redo_restores():
    tl = InjectionTimeline()
    tl.record("alpha")
    tl.undo("last")
    assert tl.text() == ""
    assert tl.redo() == UndoOp(0, "alpha")
    assert tl.text() == "alpha"


def test_record_clears_redo_and_empty():
    tl = InjectionTimeline()
    tl.record("x")
    tl.undo("last")
    tl.record("y")            # clears redo
    assert tl.redo() is None
    assert InjectionTimeline().undo("last") is None
    assert tl.text() == "y"


def test_undo_unknown_scope_removes_whole_event():
    tl = InjectionTimeline()
    tl.record("stuff")
    assert tl.undo("nonsense") == UndoOp(len("stuff"), "")   # unknown scope → full removal
    assert tl.text() == ""


# ---- session bookmarks -----------------------------------------------------

def test_bookmark_store():
    s = BookmarkStore()
    s.add("intro", 0)
    s.add("body", 42)
    s.add("intro", 5)         # update keeps order
    assert s.names() == ["intro", "body"]
    assert s.goto("body") == 42
    assert s.goto("intro") == 5
    assert s.last() == 42     # most recently *added* name is body
    assert s.goto("missing") is None
    assert BookmarkStore().last() is None


def test_parse_bookmark_command():
    assert parse_bookmark_command("bookmark here as intro") == ("add", "intro")
    assert parse_bookmark_command("bookmark here") == ("add", None)
    assert parse_bookmark_command("bookmark this called section two") == ("add", "section two")
    assert parse_bookmark_command("jump to bookmark intro") == ("goto", "intro")
    assert parse_bookmark_command("jump to my last bookmark") == ("goto", None)
    assert parse_bookmark_command("hello there") is None


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "timeline" in slugs and "bookmarks" in slugs
    assert Config().timeline.enabled is False and Config().bookmarks.enabled is False

def test_parse_timeline_command():
    from yazses.timeline.history import parse_timeline_command
    assert parse_timeline_command("undo") == ("undo", 1, "last")
    assert parse_timeline_command("undo that") == ("undo", 1, "last")
    assert parse_timeline_command("undo three") == ("undo", 3, "last")
    assert parse_timeline_command("undo 5") == ("undo", 5, "last")
    assert parse_timeline_command("redo") == ("redo", 1, "last")
    assert parse_timeline_command("redo two") == ("redo", 2, "last")
    assert parse_timeline_command("redo ten") == ("redo", 10, "last")
    assert parse_timeline_command("undo something") is None


def test_scope_reaches_the_timeline_core():
    """`InjectionTimeline.undo` has taken a scope since ADR-v2-089.

    Wiring only a repeat count leaves "undo the last word" and "undo that sentence" —
    the phrasings the feature is advertised with — unreachable.
    """
    from yazses.timeline.history import parse_timeline_command
    assert parse_timeline_command("undo the last word") == ("undo", 1, "word")
    assert parse_timeline_command("undo two words") == ("undo", 2, "word")
    assert parse_timeline_command("undo the last sentence") == ("undo", 1, "sentence")
    assert parse_timeline_command("undo the last burst") == ("undo", 1, "burst")
    assert parse_timeline_command("undo everything") == ("undo", 1, "all")


import pytest


@pytest.mark.parametrize("spoken", [
    "click undo",
    "I need to undo that",
    "press control z to undo",
    "the undo button is greyed out",
    "there is no redo",
    "hit redo",
])
def test_ordinary_speech_ending_in_undo_is_dictated_not_obeyed(spoken):
    """The command has to *be* the utterance, not merely end it.

    `commands/revise.py` anchors `_SCRATCH_RE` at both ends precisely so "scratch the
    surface" is typed rather than obeyed, and "undo" is a far more ordinary word than
    "scratch that". A pattern that only has to end the utterance silently eats every
    sentence above — and the user cannot tell a swallowed sentence from a mic failure.
    """
    from yazses.timeline.history import parse_timeline_command
    assert parse_timeline_command(spoken) is None


def test_a_misheard_number_cannot_become_a_key_flood():
    from yazses.timeline.history import MAX_REPEAT, parse_timeline_command
    action, count, scope = parse_timeline_command("undo 9999")
    assert (action, scope) == ("undo", "last")
    assert count == MAX_REPEAT


def test_trailing_punctuation_does_not_defeat_the_match():
    from yazses.timeline.history import parse_timeline_command
    assert parse_timeline_command("Undo that.") == ("undo", 1, "last")
