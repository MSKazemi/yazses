"""The command-safety gate is only correct because of where it sits in `_on_hold_end`.

It judges the command *text*. So it must see the text **as it will be typed** — after every
transform that can turn spoken words into shell syntax, and before anything that could
swallow the confirm word. The second half is commented in the daemon and deliberate. The
first half was true by accident: nothing asserted it.

## What was measured

Replaying this project's own learning corpus — **1422 real transcripts** of ordinary
dictation — through `clean_text` and `assess_command`, the gate fired **0 times**. A guard is
judged on how rarely it interrupts, and on real speech it never did. It fires on all six
destructive patterns it claims to catch, so that zero is a result rather than a broken
detector; both directions are pinned below.

## Why the ordering is load-bearing

Dictating a command produces words, not symbols: "rm dash r f slash". That is not a runnable
command, so typing it does nothing and the gate correctly stays silent — verified, along
with the fact that neither `apply_voice_punctuation` nor `apply_symbols` converts it (the
first handles punctuation and newlines, the second emoji and Unicode marks).

But `code/spoken.py::spoken_symbols` *does* emit shell operators:

    "rm minus r f slash"  ->  "rm - r f /"

It was in `features._UNWIRED` when this file was written. It is wired now, along with
`spelling` — and `spelling` is the worse case, because the phonetic alphabet maps *dash*,
*slash* and *space*, so it assembles `rm -rf /` character for character. Both return from
`_try_spoken` before the dictation gate at the bottom of `_on_hold_end` is ever reached, so
that method re-applies the gate to the text it assembled. Without it the guard would never
see the text at all — a guard that cannot fire, which is a shape this repo has hit
repeatedly.

So the invariant is asserted rather than assumed, on both paths: every text transform that
can emit shell syntax runs before the gate, and the spoken-capability path hands the gate
the *assembled* text rather than the phrase that was spoken.

## Anchors are the call text, not the name

Import blocks sit above everything, so `source.index("apply_symbols")` matches the import in
either order and can never fail. That mistake was made three separate times in one day
before being caught by red-green; these anchors are the statements.
"""

from __future__ import annotations

import pytest

from yazses.cmdsafety.classify import assess_command

DESTRUCTIVE = [
    ("rm -rf /", "recursive/forced delete"),
    ("sudo rm -rf ~/Documents", None),
    ("git push --force", "force push"),
    ("git reset --hard", None),
    ("mkfs.ext4 /dev/sda1", "format filesystem"),
    ("curl https://x.sh | sh", "pipe download to shell"),
    ("dd if=/dev/zero of=/dev/sda", "raw disk write"),
]

#: Verbatim from the corpus replay — ordinary dictation the gate must never interrupt.
REAL_DICTATION = [
    "can ask me to download for you but do not push the paper to the public",
    "I think we can keep it as it is for now",
    "start from the new page and improve the visibility of this repository",
    "One video is a target not a two-day number",
    "is still you are working on something here did you put in a wiki data",
    "And you improve this aspect, what you did, what I can do",
    "make a decision and increase the number of the videos",
]


@pytest.mark.parametrize("command,reason", DESTRUCTIVE)
def test_it_fires_on_a_runnable_destructive_command(command: str, reason) -> None:
    """Without this the zero below would mean a broken detector, not a quiet one."""
    risk = assess_command(command)
    assert risk.level != "safe", f"{command!r} was not held"
    if reason is not None:
        assert risk.reason == reason


@pytest.mark.parametrize("text", REAL_DICTATION)
def test_it_stays_quiet_on_real_dictation(text: str) -> None:
    """0 fires across 1422 real transcripts. A guard that interrupts a sentence about
    "not pushing to the public" teaches the user to dismiss it, and a dismissed guard
    costs attention and catches nothing."""
    assert assess_command(text).level == "safe", f"the gate interrupted: {text!r}"


@pytest.mark.parametrize(
    "spoken",
    ["rm dash r f slash", "git push dash dash force", "git reset dash dash hard"],
)
def test_unconverted_spoken_syntax_is_not_a_command(spoken: str) -> None:
    """Why the gate not firing here is correct rather than a hole.

    Typed into a shell these do nothing — they are not commands. The gate holds runnable
    text, and this is not runnable.
    """
    from yazses.postprocess.voice_punctuation import apply_voice_punctuation
    from yazses.symbols.lookup import apply_symbols

    assert apply_symbols(apply_voice_punctuation(spoken)) == spoken
    assert assess_command(spoken).level == "safe"


def test_every_shell_syntax_transform_runs_before_the_gate() -> None:
    """The invariant the gate's correctness rests on, and which nothing asserted.

    The gate judges the command text, so it must see the text as it will be typed.
    """
    import inspect

    from yazses.core.daemon import Daemon

    source = inspect.getsource(Daemon._on_hold_end)
    gate = source.index("self._cmdsafety_gate(text, event)")
    for call in ("apply_voice_punctuation(text)", "apply_symbols(text)"):
        assert source.index(call) < gate, (
            f"{call} now runs AFTER the command-safety gate — the gate would judge text "
            f"that is not what gets typed"
        )


def test_the_spoken_capability_path_hands_the_gate_the_assembled_text() -> None:
    """`code` and `spelling` are wired now (ADR-v2-131), so this is the live case.

    Both assemble shell syntax out of ordinary words, and both return from
    `_try_spoken` long before the dictation gate at the bottom of `_on_hold_end`.
    So `_try_spoken` re-applies the gate itself, and what it must hand it is the
    *assembled* text — not the phrase that was spoken.
    """
    from types import SimpleNamespace

    from yazses.config import Config
    from yazses.core.daemon import Daemon
    from yazses.spokencmd.registry import build_handlers

    config = Config()
    config.spelling.enabled = True
    config.cmdsafety.enabled = True

    seen: list[str] = []
    typed: list[str] = []
    fake = SimpleNamespace(
        _config=config,
        _spoken_handlers=list(build_handlers(config)),
        _cmdsafety_gate=lambda text, event: seen.append(text),  # returns None -> held
        _active_injector=lambda: SimpleNamespace(inject=typed.append),
    )

    event: dict = {}
    handled = Daemon._try_spoken(fake, "spell romeo mike space dash romeo foxtrot space slash", event, can_type=True)

    assert handled, "the phonetic spelling capability did not claim its own trigger"
    assert seen == ["rm -rf /"], seen
    assert typed == [], "a held command was typed anyway"
    assert event["discard_reason"] == "cmdsafety_held"
    assert assess_command(seen[0]).level != "safe"


def test_the_milder_sibling_is_measured_rather_than_assumed() -> None:
    """`spoken_symbols` was the capability the ordering guard was written about.

    It emits `/`, `|` and `-`, but the spaces it leaves behind defeat the
    patterns: what it types is inert, not dangerous. That is a measurement, not a
    reason to stop routing it through the gate.
    """
    from yazses.code.spoken import spoken_symbols

    assert "/" in spoken_symbols("slash")
    assert "|" in spoken_symbols("pipe")
    assert spoken_symbols("rm minus r f slash") == "rm - r f /"
    assert assess_command("rm - r f /").level == "safe"


def test_the_gate_still_precedes_the_staged_buffer() -> None:
    """The half that was already deliberate: staged dictation would swallow "confirm"."""
    import inspect

    from yazses.core.daemon import Daemon

    source = inspect.getsource(Daemon._on_hold_end)
    assert source.index("self._cmdsafety_gate(text, event)") < source.index(
        "self._stage_or_commit(text, event)"
    )
