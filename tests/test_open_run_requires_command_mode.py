"""`run <anything>` executes, so it must not fire on the dictation path.

`commands/dispatch.py::_run_terminal` types the command **and presses Return**.
Its grammar is `^run (.+)$`, which every ordinary sentence beginning with "run"
satisfies — and `[commands] enabled` is true by default, so every dictated
utterance is classified. "Run the numbers again before Friday" was therefore
executed in whatever window had focus.

Every other command is recoverable by retyping. This one is not, which is why it
is the one that requires the command key. The closed-vocabulary rules stay
available without it: they are unambiguous whole utterances.
"""

from __future__ import annotations

import pytest

from yazses.commands.grammar import IntentType, classify
from yazses.config import CommandsConfig


@pytest.mark.parametrize("utterance", [
    "run the numbers again before Friday",
    "run kubectl get pods then call get_user_by_id in main.py",
    "run the migration script before deploying",
    "run a marathon this weekend",
])
def test_the_grammar_still_matches_prose_that_starts_with_run(utterance):
    """The grammar itself is unchanged — this documents *why* a gate is needed.

    `^run (.+)$` is anchored at both ends and still swallows a whole sentence,
    because the sentence is the argument. Narrowing the regex cannot fix this:
    a shell command and an English clause are not distinguishable by shape.
    """
    intent = classify(utterance, CommandsConfig().profile)
    assert intent.action == "run_command"
    assert intent.intent is IntentType.TERMINAL


def test_the_dangerous_action_is_the_one_that_presses_return():
    """Pins the reason this rule is singled out rather than the whole class."""
    import inspect

    from yazses.commands import dispatch

    source = inspect.getsource(dispatch._run_terminal)
    assert "run_command" in source
    assert "Return" in source, "if this stops executing, the gate can be revisited"


def test_the_daemon_refuses_open_ended_run_outside_command_mode():
    import inspect

    from yazses.core.daemon import Daemon

    source = inspect.getsource(Daemon._on_hold_end)
    assert 'intent.action == "run_command"' in source
    gate = source.index('intent.action == "run_command"')
    assert "intent = None" in source[gate:gate + 900], (
        "it must fall back to dictation, so the words are typed rather than lost"
    )


@pytest.mark.parametrize("utterance,action", [
    ("run the tests", "run_tests"),
    ("run tests", "run_tests"),
    ("run the build", "run_build"),
    ("run that", "run_last"),
])
def test_the_closed_vocabulary_commands_are_untouched(utterance, action):
    """The fix must not remove voice commands that were never ambiguous."""
    intent = classify(utterance, CommandsConfig().profile)
    assert intent.action == action
    assert intent.intent is IntentType.TERMINAL


def test_the_closed_commands_are_not_gated_by_the_daemon():
    import inspect

    from yazses.core.daemon import Daemon

    source = inspect.getsource(Daemon._on_hold_end)
    for action in ("run_tests", "run_build", "run_last"):
        assert f'== "{action}"' not in source, (
            f"{action} is unambiguous and must keep working without the command key"
        )
