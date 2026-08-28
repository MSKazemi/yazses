"""In command mode, `run <destructive>` skipped the safety gate entirely.

`test_cmdsafety_daemon.py` covers the promise on the **dictation** branch. This file
covers the branch that actually *executes*, which had no gate at all.

## The hole

`_cmdsafety_gate` was called from the dictation branch of `_on_hold_end`. A `TERMINAL`
intent goes to `cmd_dispatch` on the *other* branch, so the gate was never consulted for
it — and `dispatch._run_terminal` types `run_command`'s payload **and presses Return**.
`assess_command("rm -rf build")` returns `dangerous` on both routes; only one asked.

So the one path that runs a command rather than typing one was the unguarded path.

## Why "command mode is the confirmation" was not enough

It is a real argument — a second confirmation trains dismissal, and ADR-v2-065 judges a
guard on how rarely it fires. But holding the key says *"this is a command"*, not *"and I
accept this particular one"*, and the gate exists because a **misheard** command is as
dangerous as an unintended one. Holding a key does not protect against mishearing.

The friction is measurable and near-zero: `assess_command` fires on 0 of 1422 real
dictations from this project's own corpus.

## The second bug, which the first fix would have created

Command mode discards what it cannot classify. "confirm" is not a command, so it reaches
`classify()` as DICTATE, falls through every handler, and is dropped as
`command_unmatched`. A gate that held the command but let command mode swallow the
release word would be strictly worse than no gate: the command is lost *and* the user
cannot tell why. `_cmdsafety_answer` is checked before those handlers for that reason.

## What is deliberately NOT gated

`run_tests` and `run_build` expand to fixed strings the project chose (`pytest`,
`make build`), not to anything the user said — gating them is friction that protects
nobody. `run_last` presses Up+Return and re-runs whatever the shell last had: genuinely
risky and genuinely unassessable, since the daemon cannot see the shell's history. It is
left alone rather than guarded by a check that could only guess.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from yazses.cmdsafety.classify import assess_command
from yazses.commands.grammar import IntentType, classify
from yazses.config import CmdsafetyConfig, Config
from yazses.core.daemon import Daemon
from yazses.platform import get_platform

#: What a user says, and what `_run_terminal` would type-and-Return without a gate.
SPOKEN = "run rm -rf build"
PAYLOAD = "rm -rf build"


def _daemon(mocker, enabled: bool = True):
    cfg = replace(Config(), cmdsafety=CmdsafetyConfig(enabled=enabled))
    d = Daemon(config=cfg, platform=get_platform())
    d._notify_cmdsafety = mocker.MagicMock()
    return d


def _intent(text: str = SPOKEN):
    return classify(text, Config().commands.profile)


# ------------------------------------------------------------------ the premise


def test_the_spoken_phrase_really_does_reach_the_terminal_dispatch() -> None:
    """Without this, every assertion below could be about a phrase that never routes.

    The gate is only worth testing on the branch the phrase actually takes.
    """
    intent = _intent()
    assert intent.intent is IntentType.TERMINAL
    assert intent.action == "run_command"
    assert intent.args["cmd"] == PAYLOAD


def test_the_payload_is_dangerous_by_the_same_classifier_the_other_branch_uses() -> None:
    """The asymmetry that was the defect: one verdict, two routes, one of them asking."""
    assert assess_command(PAYLOAD).level == "dangerous"


def test_run_terminal_would_press_return() -> None:
    """Why this branch and not another: it executes rather than types.

    Read off the source so the claim cannot rot silently if the dispatcher changes.
    """
    import inspect

    from yazses.commands import dispatch as dispatch_mod

    source = inspect.getsource(dispatch_mod._run_terminal)
    assert '"Return"' in source


# ------------------------------------------------------------------- the gate


def test_a_dangerous_command_does_not_dispatch(mocker) -> None:
    """The headline: `run rm -rf build` in command mode no longer reaches the shell."""
    d = _daemon(mocker)
    event: dict = {}
    assert d._cmdsafety_command_gate(_intent(), event) is False
    assert event["cmdsafety_action"] == "held"
    assert event["cmdsafety_reason"] == "recursive/forced delete"
    assert d._cmdsafety.pending == PAYLOAD


def test_an_ordinary_command_dispatches_untouched(mocker) -> None:
    """The opposite failure: a gate that fires on ordinary use teaches dismissal."""
    d = _daemon(mocker)
    event: dict = {}
    assert d._cmdsafety_command_gate(_intent("run pytest"), event) is True
    assert "cmdsafety_action" not in event
    assert d._cmdsafety.pending is None


@pytest.mark.parametrize("phrase", ["run tests", "run the build"])
def test_the_fixed_string_commands_are_not_gated(mocker, phrase: str) -> None:
    """They expand to strings the project chose, not to anything the user said."""
    d = _daemon(mocker)
    intent = classify(phrase, Config().commands.profile)
    assert intent.action != "run_command", "this phrase is meant to be a fixed-string action"
    assert d._cmdsafety_command_gate(intent, {}) is True


def test_a_run_command_with_an_empty_payload_is_not_held(mocker) -> None:
    """Nothing to assess and nothing to run — holding it would be a dead end."""
    d = _daemon(mocker)
    intent = _intent()
    empty = type(intent)(**{**intent.__dict__, "args": {"cmd": ""}})
    assert d._cmdsafety_command_gate(empty, {}) is True


# --------------------------------------------------- releasing a held command


def test_confirm_reruns_it_as_a_command_so_return_is_pressed(mocker) -> None:
    """The release must EXECUTE, not type the command onto the prompt and stop.

    Typing it would be safer and is a different feature — one the user cannot tell apart
    from the gate having failed.
    """
    d = _daemon(mocker)
    d._cmdsafety_command_gate(_intent(), {})
    dispatched = mocker.patch("yazses.core.daemon.cmd_dispatch")
    d._active_injector = mocker.MagicMock()
    d._build_macro_context = mocker.MagicMock(return_value={})

    event: dict = {}
    assert d._cmdsafety_answer("confirm", event) is True
    assert event["cmdsafety_action"] == "confirm"
    assert dispatched.call_count == 1
    assert dispatched.call_args.args[0].args["cmd"] == PAYLOAD
    assert d._cmdsafety.pending is None
    assert d._cmdsafety_intent is None


def test_cancel_discards_it_and_dispatches_nothing(mocker) -> None:
    d = _daemon(mocker)
    d._cmdsafety_command_gate(_intent(), {})
    dispatched = mocker.patch("yazses.core.daemon.cmd_dispatch")

    event: dict = {}
    assert d._cmdsafety_answer("cancel", event) is True
    assert event["cmdsafety_action"] == "cancel"
    assert dispatched.call_count == 0
    assert d._cmdsafety.pending is None
    assert d._cmdsafety_intent is None


def test_anything_else_discards_it_rather_than_leaving_the_daemon_modal(mocker) -> None:
    """A user whose "confirm" was misheard must not find command mode dead.

    Losing a dangerous command costs one re-dictation. Running one by accident does not
    have a bounded cost, so the implicit cancel goes the safe way.
    """
    d = _daemon(mocker)
    d._cmdsafety_command_gate(_intent(), {})
    dispatched = mocker.patch("yazses.core.daemon.cmd_dispatch")

    event: dict = {}
    # False: the burst was not consumed, so command mode goes on to handle it normally.
    assert d._cmdsafety_answer("open the file", event) is False
    assert event["cmdsafety_action"] == "implicit_cancel"
    assert dispatched.call_count == 0
    assert d._cmdsafety.pending is None
    assert d._cmdsafety_intent is None


def test_the_answer_check_is_inert_when_nothing_is_held(mocker) -> None:
    """It runs before every command-mode handler, so it must cost nothing normally."""
    d = _daemon(mocker)
    event: dict = {}
    assert d._cmdsafety_answer("confirm", event) is False
    assert event == {}


# ------------------------------------------- the release word is not swallowed


def test_confirm_would_otherwise_be_discarded_by_command_mode() -> None:
    """The reason `_cmdsafety_answer` runs before the handlers, stated as a fact.

    "confirm" classifies as DICTATE, so in command mode it reaches the fall-through that
    drops an unmatched phrase. If this ever stops being true, the early check can move.
    """
    assert classify("confirm", Config().commands.profile).intent is IntentType.DICTATE


def test_the_answer_check_runs_before_the_command_mode_handlers() -> None:
    """Order is the whole point: after them, the release word is already discarded."""
    import inspect

    source = inspect.getsource(Daemon._on_hold_end)
    # Named first, so a vanished anchor fails with a sentence rather than a ValueError
    # from `index` — the same reason the write guards in the mic-level tests do it.
    assert "self._cmdsafety_answer(text, event)" in source, (
        "the command-mode release check is gone; a held command can never be confirmed"
    )
    answer = source.index("self._cmdsafety_answer(text, event)")
    discard = source.index('event["discard_reason"] = "command_unmatched"')
    assert answer < discard, (
        "the release word is being discarded as an unmatched command before the gate "
        "sees it — the held command can then never be confirmed"
    )


def test_the_gate_runs_before_the_command_dispatches() -> None:
    """The anchor is the CALL, not the name — `cmd_dispatch` is also imported at module
    scope, so matching on the bare name compares against the import and can never fail.
    """
    import inspect

    source = inspect.getsource(Daemon._on_hold_end)
    assert "self._cmdsafety_command_gate(intent, event)" in source, (
        "the command branch is ungated again — `run <destructive>` types and presses "
        "Return with nothing asking"
    )
    guard = source.index("self._cmdsafety_command_gate(intent, event)")
    dispatch = source.index("cmd_dispatch(intent, injector,")
    assert guard < dispatch


# ------------------------------------------------------------------ opt-in only


def test_nothing_changes_when_the_feature_is_off(mocker) -> None:
    """It is off by default, and the 100% of installs that never enable it must not
    acquire a confirmation step."""
    assert Config().cmdsafety.enabled is False

    source = __import__("inspect").getsource(Daemon._on_hold_end)
    assert "self._cmdsafety_command_gate(intent, event)" in source, (
        "the command branch is ungated again"
    )
    guard = source.index("self._cmdsafety_command_gate(intent, event)")
    # The call sits inside a `[cmdsafety] enabled` test rather than running always.
    window = source[max(0, guard - 300):guard]
    assert "self._config.cmdsafety.enabled" in window
