"""Session Bookmarks reach the daemon through the spoken-capability door (ADR-v2-090).

The core (`bookmarks/store.py`, `caret.py`) and its tests predate this file; what is
tested here is what was missing: the flag, the trigger, the safety of the trigger, the
service that joins the store to a caret backend, and the daemon branch.

"bookmark" is an ordinary English word, so most of this file is the negative direction:
prose that merely contains it must never be claimed, and nothing here may type.
"""

from __future__ import annotations

import sys

import pytest

from yazses.bookmarks.caret import Caret
from yazses.bookmarks.service import BookmarkService
from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.platform import get_platform
from yazses.spokencmd.registry import build_handlers, enabled_slugs
from yazses.spokencmd.router import route
from yazses.system import features

DOC = "gedit:notes.txt"


class FakeCaret:
    def __init__(self, caret: Caret | None):
        self._caret = caret
        self.moves: list[Caret] = []

    def caret(self):
        return self._caret

    def move_to(self, caret):
        self.moves.append(caret)
        self._caret = caret
        return True


def _on() -> Config:
    cfg = Config()
    cfg.bookmarks.enabled = True
    return cfg


def _handlers():
    return list(build_handlers(_on()))


# ---- off by default ----------------------------------------------------------


def test_off_in_a_default_config_and_claims_nothing():
    assert "bookmarks" not in enabled_slugs(Config())
    assert route("bookmark here as intro", list(build_handlers(Config()))) is None


def test_enabling_it_enables_nothing_else():
    assert enabled_slugs(_on()) == ("bookmarks",)


# ---- the phrases -------------------------------------------------------------


@pytest.mark.parametrize(
    ("phrase", "action"),
    [
        ("bookmark here as intro", ("bookmark_add", "intro")),
        ("Bookmark here.", ("bookmark_add", None)),
        ("bookmark this called chapter two", ("bookmark_add", "chapter two")),
        ("jump to my last bookmark", ("bookmark_goto", None)),
        ("Jump to bookmark intro.", ("bookmark_goto", "intro")),
    ],
)
def test_a_bookmark_phrase_becomes_an_action_and_never_text(phrase, action):
    result = route(phrase, _handlers())
    assert result is not None
    assert result.slug == "bookmarks"
    assert result.action == action
    assert result.text is None, "a bookmark must never put text in the document"


@pytest.mark.parametrize(
    "prose",
    [
        "I'll bookmark this page for later",
        "go back to the bookmark folder",
        "click bookmark",
        "the bookmark",
        "please bookmark here as intro for me",
        "remember to jump to the bookmark bar",
        "she kept a leather bookmark in the novel",
        "I want to bookmark",
        "bookmarks are useful",
        "we jump to my last bookmark whenever",
    ],
)
def test_ordinary_prose_containing_the_word_is_never_claimed(prose):
    assert route(prose, _handlers()) is None


@pytest.mark.parametrize("phrase", ["go to bookmark intro", "go to my last bookmark"])
def test_go_to_is_left_to_the_window_focus_grammar_that_claims_it_first(phrase):
    """`_try_window_focus` runs earlier and takes "go to <anything>".

    Claiming it here would mean the phrase did one thing on X11 and another on
    Wayland, so the bookmark handler declines it everywhere.
    """
    assert route(phrase, _handlers()) is None


def test_it_works_with_nowhere_to_type_because_it_types_nothing():
    assert route("bookmark here", _handlers(), can_type=False) is not None


# ---- the service -------------------------------------------------------------


def test_add_then_jump_back_moves_the_caret_once():
    backend = FakeCaret(Caret(DOC, 120))
    svc = BookmarkService(lambda: backend)
    assert svc.add("intro") == "Bookmarked 'intro'."
    backend._caret = Caret(DOC, 4000)
    assert svc.goto("intro") == "Jumped to 'intro'."
    assert backend.moves == [Caret(DOC, 120)]


def test_a_nameless_goto_returns_to_the_most_recent_bookmark():
    backend = FakeCaret(Caret(DOC, 10))
    svc = BookmarkService(lambda: backend)
    svc.add("a")
    backend._caret = Caret(DOC, 99)
    svc.add("b")
    backend._caret = Caret(DOC, 500)
    assert svc.goto(None) == "Jumped to the last bookmark."
    assert backend.moves == [Caret(DOC, 99)]


def test_unnamed_bookmarks_get_distinct_names():
    backend = FakeCaret(Caret(DOC, 1))
    svc = BookmarkService(lambda: backend)
    assert svc.add(None) == "Bookmarked 'bookmark 1'."
    assert svc.add(None) == "Bookmarked 'bookmark 2'."


def test_no_backend_refuses_honestly_and_moves_nothing():
    svc = BookmarkService(lambda: None)
    assert "no caret backend" in svc.add("x")
    assert "no caret backend" in svc.goto("x")


def test_unknown_name_and_other_document_both_refuse():
    backend = FakeCaret(Caret(DOC, 5))
    svc = BookmarkService(lambda: backend)
    svc.add("here")
    assert "no bookmark by that name" in svc.goto("nowhere")
    backend._caret = Caret("firefox:other", 1)
    assert "different document" in svc.goto("here")
    assert backend.moves == []


def test_a_backend_factory_that_raises_degrades_to_a_refusal():
    def boom():
        raise RuntimeError("no accessibility bus")

    assert "no caret backend" in BookmarkService(boom).add("x")


def test_the_backend_is_probed_once_and_only_on_first_use():
    calls: list[int] = []

    def factory():
        calls.append(1)
        return FakeCaret(Caret(DOC, 1))

    svc = BookmarkService(factory)
    assert calls == []
    svc.add("a")
    svc.add("b")
    assert calls == [1]


# ---- the daemon branch -------------------------------------------------------


def _daemon(cfg: Config) -> Daemon:
    return Daemon(config=cfg, platform=get_platform())


def test_a_default_daemon_builds_no_service_and_ignores_the_phrase():
    d = _daemon(Config())
    assert d._bookmarks is None
    assert d._try_spoken("bookmark here", {}, can_type=True) is False
    assert d._bookmarks is None


def test_the_daemon_bookmarks_and_jumps_without_typing(mocker):
    d = _daemon(_on())
    backend = FakeCaret(Caret(DOC, 42))
    mocker.patch("yazses.bookmarks.service._default_backend", return_value=backend)
    injector = mocker.MagicMock()
    mocker.patch.object(d, "_active_injector", return_value=injector)
    said = mocker.patch.object(d, "_notify_spoken")

    event: dict = {}
    assert d._try_spoken("bookmark here as intro", event, can_type=True) is True
    assert event["spoken_action"] == "bookmark_add"
    backend._caret = Caret(DOC, 900)
    assert d._try_spoken("jump to bookmark intro", {}, can_type=True) is True

    assert backend.moves == [Caret(DOC, 42)]
    injector.inject.assert_not_called()
    injector.inject_key_sequence.assert_not_called()
    assert [c.args[0] for c in said.call_args_list] == [
        "Bookmarked 'intro'.",
        "Jumped to 'intro'.",
    ]


# ---- registry / laziness -----------------------------------------------------


def test_the_feature_is_wired_and_enableable():
    assert "bookmarks" not in features.unwired_slugs()
    assert "bookmarks" in features.SPOKEN_COMMAND_SLUGS


def test_the_bookmark_code_is_not_imported_by_a_default_registry_build():
    """A default config pays nothing: the cores are imported inside the builder."""
    for mod in [m for m in sys.modules if m.startswith("yazses.bookmarks")]:
        del sys.modules[mod]
    list(build_handlers(Config()))
    assert not [m for m in sys.modules if m.startswith("yazses.bookmarks")]
