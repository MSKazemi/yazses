"""A tray that dies must say why, in the log, without being re-run by hand.

Found on a live machine. The daemon log for one evening contained:

    21:33:00 Tray supervisor: tray is not running — relaunching
    21:33:20 Tray supervisor: tray is not running — relaunching
    21:34:00 Tray supervisor: tray is not running — relaunching
    22:29:20 Tray supervisor: tray is not running — relaunching

Four relaunches, three of them inside ninety seconds, and **not one word about the
cause** — because both launch sites passed ``stderr=subprocess.DEVNULL``. The tray is a
separate process; everything it printed on the way down went to /dev/null.

The give-up branch made the same omission self-documenting:

    "tray died 5 times; not relaunching again.
     Start it manually with `yazses tray` to see the error it prints."

That advice exists *only* because the error was discarded. The supervisor knows the tray
prints one, throws it away five times, and then asks the user to reproduce the failure by
hand — on a machine where the icon has already been missing for two minutes, and where
the whole point of the supervisor is that the icon vanishing is otherwise invisible.

This also matters beyond the terminal: the daemon log is what `yazses report` attaches to
an issue, so "the tray keeps dying" arrived as a bug report with no evidence in it.

## Scope

`describe_exit` is pure and tested here directly. The wiring — truncate-per-launch,
DEVNULL fallback — is tested through the daemon's own helpers rather than by starting a
real tray, which needs a display.
"""

from __future__ import annotations

import subprocess

from yazses.tray.supervisor import STDERR_TAIL_LINES, decide, describe_exit

QT_PLUGIN_FAILURE = (
    "qt.qpa.plugin: Could not load the Qt platform plugin \"xcb\" in \"\" even though "
    "it was found.\n"
    "This application failed to start because no Qt platform plugin could be "
    "initialized.\n"
)


def test_a_real_qt_failure_survives_the_summary() -> None:
    """The commonest way a tray dies on Linux, and the message that names the fix."""
    summary = describe_exit(QT_PLUGIN_FAILURE)
    assert "xcb" in summary
    assert "no Qt platform plugin" in summary


def test_it_keeps_the_tail_not_the_head() -> None:
    """The exception type and message are printed last; a head-first cut loses them."""
    text = "Traceback (most recent call last):\n" + "".join(
        f'  File "x.py", line {i}, in f\n' for i in range(40)
    ) + "ModuleNotFoundError: No module named 'PySide6'\n"
    summary = describe_exit(text)
    assert "ModuleNotFoundError" in summary, "dropped the one line that names the cause"
    assert len(summary.splitlines()) <= STDERR_TAIL_LINES


def test_the_traceback_banner_is_dropped() -> None:
    """It costs a line of the budget and says nothing the frames below do not."""
    assert "Traceback (most recent call last)" not in describe_exit(
        "Traceback (most recent call last):\nValueError: boom\n"
    )


def test_silence_stays_silent() -> None:
    """A tray killed by SIGKILL prints nothing; inventing a reason would be worse."""
    assert describe_exit("") == ""
    assert describe_exit("\n  \n\n") == ""


def test_the_give_up_branch_still_fires() -> None:
    """The premise: there is a bounded budget, and it ends. Unchanged by this fix."""
    assert decide(alive=False, relaunches_so_far=0).relaunch is True
    end = decide(alive=False, relaunches_so_far=5)
    assert end.give_up is True and end.relaunch is False
    assert decide(alive=True, relaunches_so_far=0).relaunch is False


# ---- the daemon wiring, without a display ---------------------------------


class _FakePaths:
    def __init__(self, tmp_path):
        self.data_dir = tmp_path


class _Daemon:
    """Just the three helpers under test, bound to a temp data dir."""

    def __init__(self, tmp_path):
        from yazses.core.daemon import Daemon

        self._platform = type("P", (), {"paths": _FakePaths(tmp_path)})()
        for name in ("_tray_stderr_path", "_open_tray_stderr", "_last_tray_error"):
            setattr(self, name, getattr(Daemon, name).__get__(self))


def test_the_captured_stderr_reaches_the_log_line(tmp_path) -> None:
    """End to end through the real helpers: a tray writes, the daemon reads it back."""
    daemon = _Daemon(tmp_path)
    handle = daemon._open_tray_stderr()
    assert handle is not subprocess.DEVNULL, "could not open a capture file at all"
    handle.write(QT_PLUGIN_FAILURE)
    handle.close()

    reported = daemon._last_tray_error()
    assert "it said:" in reported
    assert "xcb" in reported
    # Indented under the log line rather than flush left, so a multi-line Qt failure
    # does not read as several separate daemon events.
    assert "\n    " in reported


def test_each_launch_starts_a_clean_file(tmp_path) -> None:
    """The question is why the tray that just died died — not the previous six."""
    daemon = _Daemon(tmp_path)
    first = daemon._open_tray_stderr()
    first.write("ancient failure from an hour ago\n")
    first.close()

    second = daemon._open_tray_stderr()
    second.close()
    assert "ancient failure" not in daemon._last_tray_error()


def test_no_file_is_not_an_error(tmp_path) -> None:
    """The first tick of every session, and every session where the tray is healthy."""
    assert _Daemon(tmp_path)._last_tray_error() == ""


def test_an_unwritable_location_falls_back_to_devnull(tmp_path) -> None:
    """A tray whose error cannot be captured must still launch.

    That is the status quo, and it is strictly better than the diagnostics taking the
    icon down with them.
    """
    blocked = tmp_path / "not-a-dir"
    blocked.write_text("I am a file", encoding="utf-8")
    daemon = _Daemon(blocked / "sub")
    assert daemon._open_tray_stderr() is subprocess.DEVNULL
    assert daemon._last_tray_error() == ""
