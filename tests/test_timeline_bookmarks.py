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
