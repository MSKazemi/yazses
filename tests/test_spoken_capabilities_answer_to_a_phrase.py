"""Six capabilities that had a tested core and no caller, wired at one door (ADR-v2-131).

`spelling`, `code`, `math`, `snippets`, `spokenregex` and `voicetimer` each shipped a
pure, unit-tested module that nothing imported: `yazses features enable spelling`
refused, and the feature page said "not possible yet". The cores are not retested
here — they were already green. What is tested is everything that was missing:
the trigger, the flag, the ordering, and the two ways this wiring could be worse
than leaving them unwired.

**One: prose gets rewritten.** `math/latex.py` says in its own docstring that it is
"not safe to wire onto the dictation path as it stands", because its keywords are
ordinary English — "she squared her shoulders" becomes "she^{2} her shoulders".
Every trigger is therefore a required leading verb anchored at both ends, and the
prose cases from that docstring are pinned below as phrases nothing may claim.

**Two: a safety guard stops seeing the text.** The phonetic alphabet maps *dash*,
*slash* and *space*, so "spell romeo mike space dash romeo foxtrot space slash"
assembles `rm -rf /` exactly. That is produced on the command path, which returns
long before the Command Safety Gate on the dictation path, so the gate is re-applied
here — `test_the_safety_gate_still_sees_what_spelling_assembles` fails if that call
is ever removed.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from yazses.config import CmdsafetyConfig, Config
from yazses.core.daemon import Daemon
from yazses.platform import get_platform
from yazses.spokencmd.registry import build_handlers, enabled_slugs, tighten_code
from yazses.spokencmd.router import SpokenHandler, prefixed, route
from yazses.spokencmd.timers import TimerService

ALL_SIX = ("spelling", "code", "math", "spokenregex", "snippets", "voicetimer")


def _config(*slugs: str, snippets: dict | None = None) -> Config:
    cfg = Config()
    for slug in slugs:
        getattr(cfg, slug).enabled = True
    if snippets is not None:
        cfg.snippets.entries = dict(snippets)
    return cfg


def _handlers(*slugs: str, snippets: dict | None = None):
    return list(build_handlers(_config(*slugs, snippets=snippets)))


# ---- off by default ---------------------------------------------------------


def test_every_one_of_them_is_off_in_a_default_config():
    """New features ship off by default — a governance rule, not a preference."""
    assert enabled_slugs(Config()) == ()
    assert list(build_handlers(Config())) == []


def test_with_everything_off_no_phrase_is_claimed():
    assert route("spell alpha bravo", _handlers()) is None


def test_enabling_one_does_not_enable_its_neighbours():
    assert enabled_slugs(_config("spelling")) == ("spelling",)


# ---- each capability claims its own phrase ----------------------------------


@pytest.mark.parametrize(
    ("slug", "phrase", "expected"),
    [
        ("spelling", "spell capital alpha bravo double lima", "Abll"),
        ("code", "code def foo open paren x comma y close paren colon", "def foo(x, y):"),
        ("math", "math x squared plus y squared", "x^{2} + y^{2}"),
        ("spokenregex", "regex three digits", r"\d{3}"),
    ],
)
def test_a_capability_turns_its_phrase_into_text(slug, phrase, expected):
    result = route(phrase, _handlers(slug))
    assert result is not None, f"{slug} did not claim {phrase!r}"
    assert result.slug == slug
    assert result.text == expected


def test_a_snippet_expands_from_the_configured_store():
    result = route("insert my address", _handlers("snippets", snippets={"my address": "1 Rue de Test"}))
    assert result is not None
    assert result.text == "1 Rue de Test"


def test_a_snippet_that_is_not_in_the_store_is_declined_rather_than_typed_empty():
    """The verb matched; nothing answers to it. Falling through beats typing ""."""
    assert route("insert nothing like this", _handlers("snippets", snippets={"a": "b"})) is None


def test_a_timer_reports_itself_and_types_nothing():
    result = route("set a timer for 25 minutes", _handlers("voicetimer"))
    assert result is not None
    assert result.text is None, "a timer must never put text in the document"
    assert result.action == ("timer_set", 1500)
    assert "25 minutes" in (result.message or "")


def test_cancelling_a_timer_is_understood():
    result = route("cancel the timer", _handlers("voicetimer"))
    assert result is not None and result.action == ("timer_cancel", None)


# ---- what must never be claimed ---------------------------------------------


@pytest.mark.parametrize(
    "prose",
    [
        # The two cases named in math/latex.py's own warning.
        "she squared her shoulders and left",
        "plus I think we should go",
        # The verb appears, but not as a leading command.
        "let me spell out my reasoning for the team",
        "the pattern for success is hard work",
        "I had to insert myself into the conversation",
        "we should code review this before Friday",
        "do the math before you commit to it",
    ],
)
def test_ordinary_prose_is_never_claimed_by_any_capability(prose):
    """All six on at once — the strictest version of the question."""
    assert route(prose, _handlers(*ALL_SIX, snippets={"my address": "x"})) is None


def test_a_trigger_verb_in_the_middle_of_a_sentence_does_not_fire():
    """The documented failure: `re.search` swallowed "click undo" in an earlier PR."""
    assert route("please spell alpha for me", _handlers("spelling")) is None


def test_a_bare_trigger_verb_with_no_body_is_declined():
    assert route("spell", _handlers("spelling")) is None


def test_trailing_punctuation_whisper_adds_does_not_defeat_the_anchor():
    """Whisper writes "Spell alpha bravo." — an anchored `$` would miss the full stop."""
    result = route("Spell alpha bravo.", _handlers("spelling"))
    assert result is not None and result.text == "ab"


def test_an_empty_utterance_claims_nothing():
    assert route("", _handlers(*ALL_SIX)) is None
    assert route("   ", _handlers(*ALL_SIX)) is None


def test_prefixed_refuses_to_build_a_handler_with_no_verb():
    with pytest.raises(ValueError):
        prefixed("nope", (), lambda body: body)


# ---- no editable target ------------------------------------------------------


def test_with_nowhere_to_type_the_typing_capabilities_are_skipped():
    assert route("spell alpha bravo", _handlers("spelling"), can_type=False) is None


def test_with_nowhere_to_type_a_timer_still_works():
    """It reports through a notification, so a focused text field is irrelevant."""
    result = route("set a timer for 5 minutes", _handlers("voicetimer"), can_type=False)
    assert result is not None and result.action == ("timer_set", 300)


# ---- code spacing ------------------------------------------------------------


@pytest.mark.parametrize(
    ("spaced", "tight"),
    [
        ("def foo ( x , y ) :", "def foo(x, y):"),
        ("x = ( a + b )", "x = (a + b)"),          # `= (` must NOT close up
        ("self . name = none", "self.name = none"),
        ("items [ 0 ]", "items[0]"),
    ],
)
def test_spoken_code_is_tightened_into_something_a_compiler_accepts(spaced, tight):
    assert tighten_code(spaced) == tight


def test_tightening_leaves_ordinary_prose_alone():
    assert tighten_code("hello there") == "hello there"


# ---- the timer service -------------------------------------------------------


class _FakeTimer:
    """Records instead of sleeping; `fire()` is the clock."""

    def __init__(self, delay, fn):
        self.delay, self.fn, self.started, self.cancelled = delay, fn, False, False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True

    def fire(self):
        self.fn()


def _service():
    made: list[_FakeTimer] = []
    said: list[str] = []

    def factory(delay, fn):
        made.append(_FakeTimer(delay, fn))
        return made[-1]

    return TimerService(said.append, factory), made, said


def test_setting_a_timer_starts_one_for_the_requested_delay():
    svc, made, _ = _service()
    assert svc.set(1500, "done") is True
    assert made[0].delay == 1500.0 and made[0].started
    assert svc.pending


def test_a_fired_timer_notifies_and_stops_being_pending():
    svc, made, said = _service()
    svc.set(60, "Voice timer finished.")
    made[0].fire()
    assert said == ["Voice timer finished."]
    assert not svc.pending


def test_setting_a_second_timer_replaces_the_first():
    """Only one cancel phrase exists, so a second timer would be unstoppable by voice."""
    svc, made, _ = _service()
    svc.set(60, "a")
    svc.set(120, "b")
    assert made[0].cancelled
    assert len(made) == 2 and not made[1].cancelled


def test_cancelling_reports_whether_there_was_anything_to_cancel():
    svc, _, _ = _service()
    assert svc.cancel() is False
    svc.set(60, "x")
    assert svc.cancel() is True
    assert not svc.pending


def test_a_zero_length_timer_is_refused_rather_than_fired_at_once():
    svc, made, _ = _service()
    assert svc.set(0, "x") is False
    assert made == []


def test_a_notification_that_raises_does_not_escape_the_timer_thread():
    def explode(_message):
        raise RuntimeError("no notifier here")

    svc = TimerService(explode, lambda delay, fn: _FakeTimer(delay, fn))
    svc.set(60, "x")
    svc._pending.fire()   # would propagate out of a thread with nothing above it


def test_shutdown_is_safe_to_call_twice():
    svc, _, _ = _service()
    svc.set(60, "x")
    svc.shutdown()
    svc.shutdown()
    assert not svc.pending


# ---- the daemon wiring -------------------------------------------------------


def _daemon(cfg) -> Daemon:
    return Daemon(config=cfg, platform=get_platform())


def test_a_default_daemon_builds_no_handlers_and_handles_nothing():
    d = _daemon(Config())
    assert d._spoken_handlers == []
    assert d._try_spoken("spell alpha bravo", {}, can_type=True) is False


def test_the_daemon_types_what_a_capability_produced(mocker):
    d = _daemon(_config("spelling"))
    injector = mocker.MagicMock()
    mocker.patch.object(d, "_active_injector", return_value=injector)
    event: dict = {}
    assert d._try_spoken("spell alpha bravo", event, can_type=True) is True
    injector.inject.assert_called_once_with("ab")
    assert event["spoken_slug"] == "spelling"
    assert event["final_text"] == "ab"


def test_the_safety_gate_still_sees_what_spelling_assembles(mocker):
    """The load-bearing one.

    "romeo mike space dash romeo foxtrot space slash" spells `rm -rf /` exactly.
    This path returns before the dictation gate, so `_try_spoken` re-applies it;
    delete that call and this test types a destructive command into the shell.
    """
    cfg = replace(_config("spelling"), cmdsafety=CmdsafetyConfig(enabled=True))
    d = _daemon(cfg)
    injector = mocker.MagicMock()
    mocker.patch.object(d, "_active_injector", return_value=injector)
    d._notify_cmdsafety = mocker.MagicMock()

    event: dict = {}
    handled = d._try_spoken(
        "spell romeo mike space dash romeo foxtrot space slash", event, can_type=True
    )

    assert handled is True, "the utterance was still claimed by the spelling capability"
    injector.inject.assert_not_called()
    assert d._cmdsafety.pending == "rm -rf /"
    assert event["discard_reason"] == "cmdsafety_held"


def test_a_harmless_spelling_is_not_held_by_the_gate(mocker):
    """A guard is judged on how rarely it fires; ordinary spelling must pass."""
    cfg = replace(_config("spelling"), cmdsafety=CmdsafetyConfig(enabled=True))
    d = _daemon(cfg)
    injector = mocker.MagicMock()
    mocker.patch.object(d, "_active_injector", return_value=injector)
    assert d._try_spoken("spell alpha bravo charlie", {}, can_type=True) is True
    injector.inject.assert_called_once_with("abc")


def test_an_injector_that_raises_is_reported_not_propagated(mocker):
    d = _daemon(_config("spelling"))
    injector = mocker.MagicMock()
    injector.inject.side_effect = RuntimeError("no display")
    mocker.patch.object(d, "_active_injector", return_value=injector)
    event: dict = {}
    assert d._try_spoken("spell alpha", event, can_type=True) is True
    assert event["discard_reason"] == "spoken_inject_failed"


def test_the_daemon_sets_and_cancels_a_real_timer(mocker):
    d = _daemon(_config("voicetimer"))
    mocker.patch.object(d, "_notify_spoken")
    event: dict = {}
    assert d._try_spoken("set a timer for 10 minutes", event, can_type=False) is True
    assert event["spoken_action"] == "timer_set"
    assert d._timers is not None and d._timers.pending
    assert d._try_spoken("cancel the timer", {}, can_type=False) is True
    assert not d._timers.pending
    d._timers.shutdown()


def test_every_trigger_is_anchored_at_both_ends():
    """A structural guard: the anchor is applied by `prefixed`, not by each author.

    Handlers are built through one factory precisely so no capability can ship a
    `re.search`. This asserts the property that factory exists to guarantee.
    """
    for handler in _handlers(*ALL_SIX, snippets={"a": "b"}):
        assert isinstance(handler, SpokenHandler)
        # A verb buried mid-sentence must never be claimed by any of them.
        assert handler.match(f"I would rather not {handler.slug} anything today") is None
