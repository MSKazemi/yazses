"""ydotool 1.x and ydotool 0.1.x are different CLIs wearing the same name.

Debian and Ubuntu ship 0.1.8 (24.04 through 26.04). YazSes spoke only 1.x, so on
those machines every dictation was transcribed and then dropped:

    $ ydotool type -d 6 -H 6 -- hello
    ydotool: type: error: unrecognised option '-d'
    $ echo $?
    0

The exit code is the reason it was silent rather than merely broken -- `check=True`
never raised, `LinuxInjector`'s clipboard fallback never fired, nothing reached the
log, and `doctor` reported the backend as fine.

Every 0.1.8 behaviour asserted here was measured on Ubuntu by grabbing the ydotoold
virtual device (EVIOCGRAB) and reading the events it actually emitted.
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from yazses.inject import ydotool as yd

# `ydotool type --help` on 0.1.8 and on 1.x -- the discriminator is the hold time,
# which 0.1.x does not have at all.
HELP_V0 = (
    "Usage: type [--delay milliseconds] [--key-delay milliseconds] [--args N]"
    "[--file <filepath>] <things to type>\n"
    "  --help                    Show this help.\n"
    "  --delay milliseconds      Delay time before start typing.\n"
    "  --key-delay milliseconds  Delay time between keystrokes. Default 12ms.\n"
)
HELP_V1 = (
    "Usage: ydotool type [OPTION]... [STRINGS]...\n"
    "  -d, --key-delay <ms>   Delay between keystrokes\n"
    "  -H, --key-hold <ms>    Hold time of each keystroke\n"
)


@pytest.fixture(autouse=True)
def _clear_dialect_cache():
    yd.set_ydotool_dialect(None)
    yield
    yd.set_ydotool_dialect(None)


class _Recorder:
    """Stands in for subprocess.run and replays a scripted result per call."""

    def __init__(self, results):
        self.results = list(results)
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        if self.results:
            returncode, stderr = self.results.pop(0)
        else:
            returncode, stderr = 0, ""
        return SimpleNamespace(returncode=returncode, stdout="", stderr=stderr)


# --- the exit-0 contract ------------------------------------------------------


def test_an_option_error_is_a_failure_even_though_ydotool_exits_zero(monkeypatch):
    run = _Recorder([(0, "ydotool: type: error: unrecognised option '-d'\n")])
    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(yd.YdotoolOptionError):
        yd.run_ydotool(["ydotool", "type", "-d", "6", "--", "hi"], timeout=5)


def test_ordinary_ydotool_chatter_is_not_an_error(monkeypatch):
    # Both lines are what a SUCCESSFUL 0.1.8 run prints, on stderr.
    run = _Recorder([(0, "ydotool: notice: Using ydotoold backend\n"
                         "Key delay was set to 6 milliseconds.\n")])
    monkeypatch.setattr(subprocess, "run", run)
    yd.run_ydotool(["ydotool", "type", "--key-delay", "6", "--", "hi"], timeout=5)


def test_a_nonzero_exit_is_still_a_failure(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _Recorder([(1, "")]))
    with pytest.raises(yd.YdotoolCliError):
        yd.run_ydotool(["ydotool", "type", "--", "hi"], timeout=5)


# --- dialect detection --------------------------------------------------------


@pytest.mark.parametrize(
    ("help_text", "expected"),
    [(HELP_V0, yd.DIALECT_V0), (HELP_V1, yd.DIALECT_V1)],
)
def test_dialect_is_probed_from_type_help(monkeypatch, help_text, expected):
    def fake_run(argv, **kwargs):
        assert argv == ["ydotool", "type", "--help"]
        return SimpleNamespace(returncode=0, stdout=help_text, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert yd.ydotool_dialect() == expected


def test_the_dialect_is_probed_once(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout=HELP_V0, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    yd.ydotool_dialect()
    yd.ydotool_dialect()
    assert len(calls) == 1


# --- the two command lines ----------------------------------------------------


def test_v0_types_with_key_delay_and_never_d_or_h():
    argv = yd.YdotoolInjector()._type_argv("hello", yd.DIALECT_V0)
    assert argv == ["ydotool", "type", "--key-delay", "6", "--", "hello"]
    assert "-d" not in argv and "-H" not in argv


def test_v1_type_command_is_unchanged():
    argv = yd.YdotoolInjector()._type_argv("hello", yd.DIALECT_V1)
    assert argv == ["ydotool", "type", "-d", "6", "-H", "6", "--", "hello"]


@pytest.mark.parametrize(
    ("combo", "expected"),
    [
        ("ctrl+v", ["ctrl+v"]),
        ("ctrl+BackSpace", ["ctrl+backspace"]),
        ("shift+Down", ["shift+down"]),
        ("ctrl+shift+k", ["ctrl+shift+k"]),
        # dispatch.py sends "Return" for "new line"; 0.1.8 types the letter r for it.
        ("Return", ["enter"]),
        ("Escape", ["esc"]),
        ("F2", ["f2"]),
        ("Left", ["left"]),
        ("super+a", ["super+a"]),
    ],
)
def test_v0_key_names_are_symbolic(combo, expected):
    assert yd.ydotool_key_args_v0(combo) == expected


def test_v1_key_args_stay_numeric():
    assert yd.ydotool_key_args("ctrl+v") == ["29:1", "47:1", "47:0", "29:0"]


@pytest.mark.parametrize("combo", ["space", "KEY_RIGHTCTRL", "KEY_SEMICOLON", "KEY_DOT"])
def test_v0_refuses_a_key_it_would_mistype(combo):
    """0.1.8 has no error path: an unknown name types its first letter and exits 0.

    Raising here is what routes the keystroke to the clipboard fallback instead of
    putting a wrong character on the screen.
    """
    with pytest.raises(ValueError):
        yd.ydotool_key_args_v0(combo)


def test_key_argv_spells_the_delay_flag_per_dialect():
    assert yd.ydotool_key_argv(["ctrl+v"], yd.DIALECT_V0, 40)[:4] == [
        "ydotool", "key", "--key-delay", "40",
    ]
    assert yd.ydotool_key_argv(["ctrl+v"], yd.DIALECT_V1, 40)[:4] == [
        "ydotool", "key", "-d", "40",
    ]


# --- downgrade behaviour ------------------------------------------------------


def test_inject_downgrades_once_and_retypes(monkeypatch):
    yd.set_ydotool_dialect(yd.DIALECT_V1)
    run = _Recorder([(0, "ydotool: type: error: unrecognised option '-d'\n"), (0, "")])
    monkeypatch.setattr(subprocess, "run", run)

    yd.YdotoolInjector().inject("hi")

    assert run.calls[0][:3] == ["ydotool", "type", "-d"]
    assert run.calls[1] == ["ydotool", "type", "--key-delay", "6", "--", "hi"]
    # and the dialect stays downgraded for the next dictation
    assert yd.ydotool_dialect() == yd.DIALECT_V0


def test_a_non_option_failure_is_not_retyped(monkeypatch):
    """A command that was accepted may have typed half the text already."""
    yd.set_ydotool_dialect(yd.DIALECT_V1)
    run = _Recorder([(1, "ydotool: type: something else went wrong\n")])
    monkeypatch.setattr(subprocess, "run", run)

    with pytest.raises(yd.YdotoolCliError):
        yd.YdotoolInjector().inject("hi")
    assert len(run.calls) == 1


def test_v0_does_not_send_the_numeric_flood_guard(monkeypatch):
    """The guard is a list of bare key-ups, which 0.1.x's `key` grammar cannot express."""
    yd.set_ydotool_dialect(yd.DIALECT_V0)
    run = _Recorder([(0, "")])
    monkeypatch.setattr(subprocess, "run", run)

    yd.YdotoolInjector().inject("hi")

    assert len(run.calls) == 1
    assert run.calls[0][1] == "type"


def test_v1_still_sends_the_flood_guard(monkeypatch):
    yd.set_ydotool_dialect(yd.DIALECT_V1)
    run = _Recorder([(0, ""), (0, "")])
    monkeypatch.setattr(subprocess, "run", run)

    yd.YdotoolInjector().inject("hi")

    assert len(run.calls) == 2
    assert run.calls[1][:2] == ["ydotool", "key"]
    assert "42:0" in run.calls[1]


# --- the bare key-up guard ----------------------------------------------------


def test_the_stuck_modifier_guard_is_a_no_op_on_v0(monkeypatch):
    """`ydotool key 97:0` types the digit 9 on 0.1.8 -- measured, not assumed.

    The daemon runs this guard on every hold-end, so a pass-through put a stray
    digit into the document on every single dictation.
    """
    yd.set_ydotool_dialect(yd.DIALECT_V0)
    run = _Recorder([])
    monkeypatch.setattr(subprocess, "run", run)

    yd.release_keycodes({97, 100})

    assert run.calls == []


def test_the_stuck_modifier_guard_still_runs_on_v1(monkeypatch):
    yd.set_ydotool_dialect(yd.DIALECT_V1)
    run = _Recorder([(0, "")])
    monkeypatch.setattr(subprocess, "run", run)

    yd.release_keycodes({100, 97})

    assert run.calls == [["ydotool", "key", "97:0", "100:0"]]


# --- the fallback is no longer silent -----------------------------------------


def test_falling_back_to_the_clipboard_is_logged(caplog):
    """The whole failure was invisible; a fallback that says nothing is how."""
    import logging

    from yazses.platform.linux.injector import LinuxInjector

    injector = LinuxInjector.__new__(LinuxInjector)

    class _Broken:
        def inject(self, text):
            raise yd.YdotoolCliError("unrecognised option '-d'")

    class _Fallback:
        def __init__(self):
            self.got = []

        def inject(self, text):
            self.got.append(text)

    injector._primary = _Broken()
    injector._fallback = _Fallback()

    with caplog.at_level(logging.WARNING):
        injector.inject("hello")

    assert injector._fallback.got == ["hello"]
    assert "clipboard fallback" in caplog.text
    assert "unrecognised option" in caplog.text
