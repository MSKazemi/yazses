"""The spoken mic answer wired into the daemon (ADR-022, Spec 1).

The pure matcher and the open-question window are covered in `test_mic_prompt.py`.
What is tested here is the promise to a user who turns it on — saying "ignore"
dismisses the toast instead of typing the word into their document — and the four
ways that promise turns into a defect:

* Typing "re-calibrate" into the document because re-calibration itself failed.
* Eating "please ignore the second paragraph" as a control word.
* Answering a question nobody asked, because the window was never scoped.
* Changing behaviour for the installs that never enable it.
"""

from __future__ import annotations

import time
from dataclasses import replace

from yazses.config import AudioConfig, Config
from yazses.core.daemon import Daemon
from yazses.platform import get_platform


def _daemon(mocker, **audio):
    cfg = replace(Config(), audio=AudioConfig(voice_answer=True, **audio))
    d = Daemon(config=cfg, platform=get_platform())
    d._on_mic_action = mocker.MagicMock()
    return d


def _asked(d):
    d._mic_prompt.ask(time.time())


# ---- the promise -----------------------------------------------------------


def test_saying_ignore_dismisses_the_toast_instead_of_typing_it(mocker):
    d = _daemon(mocker)
    _asked(d)
    event: dict = {}
    assert d._mic_answer_gate("Ignore.", event) is None, "the word would have been typed"
    d._on_mic_action.assert_called_once_with("ignore")
    assert event["mic_answer"] == "ignore"


def test_the_spoken_route_reaches_the_same_handler_as_the_button(mocker):
    """One handler, so the two routes cannot drift apart."""
    for phrase, key in (("recalibrate", "recalibrate"), ("pin this mic", "pin")):
        d = _daemon(mocker)
        _asked(d)
        assert d._mic_answer_gate(phrase, {}) is None
        d._on_mic_action.assert_called_once_with(key)


def test_answering_closes_the_question(mocker):
    """A second "ignore" is prose again, not a second dismissal."""
    d = _daemon(mocker)
    _asked(d)
    d._mic_answer_gate("ignore", {})
    assert d._mic_answer_gate("ignore", {}) == "ignore"


# ---- the ways it becomes a defect ------------------------------------------


def test_prose_passes_through_untouched(mocker):
    d = _daemon(mocker)
    _asked(d)
    prose = "please ignore the second paragraph"
    assert d._mic_answer_gate(prose, {}) == prose
    d._on_mic_action.assert_not_called()


def test_an_unasked_question_is_not_answered(mocker):
    """Without this, "ignore" is a control word from daemon start."""
    d = _daemon(mocker)
    assert d._mic_answer_gate("ignore", {}) == "ignore"
    d._on_mic_action.assert_not_called()


def test_an_expired_question_types_the_word_rather_than_swallowing_it(mocker):
    """Once the window shuts the word is ordinary again — and must reach the page.

    Silently dropping it would be the worst of both: no action taken and no text.
    """
    d = _daemon(mocker, voice_answer_window_s=45.0)
    d._mic_prompt.ask(time.time() - 600.0)
    assert d._mic_answer_gate("ignore", {}) == "ignore"
    d._on_mic_action.assert_not_called()


def test_a_failing_action_still_consumes_the_utterance(mocker):
    """Otherwise a re-calibration that raises types "re-calibrate" into the document."""
    d = _daemon(mocker)
    d._on_mic_action = mocker.MagicMock(side_effect=RuntimeError("no mic"))
    _asked(d)
    assert d._mic_answer_gate("recalibrate", {}) is None


# ---- scoping the window ----------------------------------------------------


def test_only_a_toast_that_asks_something_opens_the_window(mocker):
    """Nine of the eleven notification sites are informational (`actions=False`).

    Arming "ignore" after a toast with no buttons would be a control word with
    nothing to control.
    """
    d = _daemon(mocker)
    mocker.patch("yazses.system.notify.notify")
    d._notify_mic("⌨ No place to type", "body", actions=False)
    assert d._mic_prompt.asked_at is None

    d._notify_mic("🎤 Microphone changed", "body")
    assert d._mic_prompt.asked_at is not None


# ---- position in the chain, which is load-bearing --------------------------


def test_it_runs_after_the_safety_gates_and_before_staged():
    """Both halves of that position are decisions, not accidents.

    *After* the safety gates: a held `rm -rf` keeps first claim on the utterance.
    Placed first, "ignore" would answer a mic toast while a dangerous command sat
    waiting for its own release word.

    *Before* staged dictation: the staged buffer swallows control utterances as
    ordinary text, which is the reason ADR-021 gives for the other two.
    """
    import ast
    import inspect
    import textwrap

    from yazses.core.daemon import Daemon

    tree = ast.parse(textwrap.dedent(inspect.getsource(Daemon._on_hold_end)))
    wanted = {"_cmdsafety_gate", "_checkdigit_gate", "_mic_answer_gate", "_stage_or_commit"}
    calls = [
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in wanted
    ]
    missing = sorted(wanted - set(calls))
    assert not missing, f"never reached from _on_hold_end: {missing}"
    assert calls.index("_cmdsafety_gate") < calls.index("_mic_answer_gate"), (
        "a mic answer would be consumed while a dangerous command was still held"
    )
    assert calls.index("_checkdigit_gate") < calls.index("_mic_answer_gate")
    assert calls.index("_mic_answer_gate") < calls.index("_stage_or_commit"), (
        "the staged buffer would swallow the spoken answer as ordinary text"
    )


# ---- off by default --------------------------------------------------------


def test_it_is_off_by_default():
    """AGENTS.md: new features ship off. It consumes a burst that would be typed,
    which is exactly the class of change `[cmdsafety]` and `[checkdigit]` opt into."""
    assert Config().audio.voice_answer is False
