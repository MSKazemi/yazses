"""A frozen bundle is not a Python interpreter, and the stdlib assumes it is.

From the first end-to-end macOS run (#182). Every command in that terminal log
was framed by::

    multiprocessing/resource_tracker.py:147: UserWarning: resource_tracker:
      process died unexpectedly, relaunching.  Some resources might leak.
    Usage: YazSes [OPTIONS] COMMAND [ARGS]...
    ╭─ Error ─────────────────────────────────────────────────╮
    │ No such option: -B                                      │
    ╰─────────────────────────────────────────────────────────╯

including the runs that otherwise *succeeded* -- the dictation chain reported
captured, heard and cleaned in between two copies of that error. It reads as a
broken CLI and is not one.

``multiprocessing.resource_tracker`` relaunches ``sys.executable`` with the
current interpreter flags and ``-c <program>``. In a PyInstaller bundle
``sys.executable`` is the bundle, and PyInstaller's bootloader sets
``dont_write_bytecode``, so the child re-enters `main()` as
``["-B", "-c", "from multiprocessing.resource_tracker import main;main(9)"]``.
Nothing matched it, so it fell through to Typer, which rejected ``-B`` and
exited -- killing the tracker, which Python then relaunched, forever.

The parsing is pure and tested here. What is *not* asserted is the bundle's
behaviour end to end: that needs a frozen build on a Mac, which is #182.
"""

from __future__ import annotations

import pytest

from yazses.__main__ import _handle_interpreter_reentry, interpreter_reentry

TRACKER = "from multiprocessing.resource_tracker import main;main(9)"


# ---- the shape that was actually reported -------------------------------


def test_the_exact_argv_from_the_182_log_is_recognised() -> None:
    assert interpreter_reentry(["-B", "-c", TRACKER]) == TRACKER


@pytest.mark.parametrize(
    "flags",
    [
        [],  # no flags set
        ["-B"],  # PyInstaller's bootloader — the reported case
        ["-E", "-s"],  # isolated-ish
        ["-B", "-Wignore", "-Xdev"],  # single-token -W/-X, as the stdlib emits
        ["-O", "-OO", "-B"],
    ],
)
def test_any_leading_interpreter_flags_are_skipped(flags: list[str]) -> None:
    """`_args_from_interpreter_flags` output varies with how Python was started,
    so pinning only `-B` would fix this Mac and not the next one."""
    assert interpreter_reentry([*flags, "-c", TRACKER]) == TRACKER


# ---- and the shapes that must keep reaching the CLI ---------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["doctor"],
        ["--cli", "doctor"],
        ["--daemon"],
        ["--tray"],
        ["transcribe", "-v", "meeting.wav"],  # a short flag, but not a re-entry
        ["--version"],
        [],
    ],
)
def test_real_invocations_are_not_mistaken_for_a_reentry(argv: list[str]) -> None:
    assert interpreter_reentry(argv) is None


def test_a_bare_c_with_no_program_is_not_a_reentry() -> None:
    """Malformed. Better a CLI usage error than `exec(None)`."""
    assert interpreter_reentry(["-B", "-c"]) is None


def test_a_long_option_stops_the_scan() -> None:
    """`--cli -c foo` is a YazSes command line, not an interpreter one."""
    assert interpreter_reentry(["--cli", "-c", TRACKER]) is None


# ---- the gate: only a frozen bundle ever executes anything ---------------


def test_an_unfrozen_process_never_executes_the_program(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pip-installed `yazses` is launched through a console script and cannot
    receive this argv from the stdlib. Executing it there would turn a typo into
    arbitrary code, so the gate is the security boundary, not an optimisation."""
    monkeypatch.delattr("sys.frozen", raising=False)
    monkeypatch.setattr("sys.argv", ["yazses", "-B", "-c", "raise AssertionError"])
    assert _handle_interpreter_reentry() is False


def test_a_frozen_process_runs_the_program_and_says_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    marker = tmp_path / "ran.txt"
    program = f"import pathlib; pathlib.Path({str(marker)!r}).write_text('yes')"
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr("sys.argv", ["YazSes", "-B", "-c", program])

    assert _handle_interpreter_reentry() is True
    assert marker.read_text() == "yes", "the relaunched program did not run"


def test_a_frozen_process_still_hands_real_commands_to_the_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bundle's own dispatch must survive the new branch in front of it."""
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr("sys.argv", ["YazSes", "--cli", "doctor"])
    assert _handle_interpreter_reentry() is False


def test_the_program_sees_the_argv_python_would_have_given_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """`python -c` sets argv[0] to "-c". Leaving YazSes's own argv in place would
    hand the relaunched program a command line meant for something else."""
    marker = tmp_path / "argv.txt"
    program = f"import sys, pathlib; pathlib.Path({str(marker)!r}).write_text(repr(sys.argv))"
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr("sys.argv", ["YazSes", "-B", "-c", program])

    assert _handle_interpreter_reentry() is True
    assert marker.read_text() == repr(["-c"])
