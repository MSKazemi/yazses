"""Std streams that may be absent.

PyInstaller sets sys.stdout/stderr/stdin to None in a windowed (GUI-subsystem)
build. Every unguarded `sys.stdout.isatty()` is then an AttributeError, which
Windows surfaces as an "Unhandled exception in script" dialog. These lock in
that a missing stream degrades rather than raises.
"""

from __future__ import annotations

import io
import sys

import pytest

from yazses.system import streams


class _Exploding(io.StringIO):
    """A stream that has been closed/detached under us."""

    def isatty(self):
        raise ValueError("I/O operation on closed file")


# ---- is_a_tty ----------------------------------------------------------


def test_none_stream_is_not_a_tty():
    assert streams.is_a_tty(None) is False


def test_broken_stream_is_not_a_tty():
    assert streams.is_a_tty(_Exploding()) is False


def test_real_tty_is_reported():
    class _Tty(io.StringIO):
        def isatty(self):
            return True

    assert streams.is_a_tty(_Tty()) is True


def test_pipe_is_not_a_tty():
    assert streams.is_a_tty(io.StringIO()) is False


# ---- the module-level accessors ---------------------------------------


def test_stdout_isatty_survives_a_none_stdout(monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    assert streams.stdout_isatty() is False


def test_stdin_isatty_survives_a_none_stdin(monkeypatch):
    monkeypatch.setattr(sys, "stdin", None)
    assert streams.stdin_isatty() is False


def test_accessors_survive_a_deleted_attribute(monkeypatch):
    """Embedders occasionally delete the attribute outright rather than
    setting it to None."""
    monkeypatch.delattr(sys, "stdout", raising=False)
    assert streams.stdout() is None
    assert streams.stdout_isatty() is False


# ---- write_out ---------------------------------------------------------


def test_write_out_writes_verbatim(monkeypatch):
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    assert streams.write_out("alpha\nbeta\n") is True
    # byte-exact: no added newline (yazses vocab export round-trips this)
    assert buf.getvalue() == "alpha\nbeta\n"


def test_write_out_reports_failure_when_there_is_no_stdout(monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    assert streams.write_out("anything") is False


def test_write_out_swallows_a_broken_pipe(monkeypatch):
    class _BrokenPipe(io.StringIO):
        def write(self, _s):
            raise BrokenPipeError(32, "Broken pipe")

    monkeypatch.setattr(sys, "stdout", _BrokenPipe())
    assert streams.write_out("x") is False


# ---- the windowed-build safety net ------------------------------------


def test_ensure_streams_binds_every_missing_stream(monkeypatch):
    """Off Windows there is no parent console to attach, so this is the
    devnull fallback path — the invariant is only that nothing stays None."""
    from yazses.system import wincon

    for name in ("stdout", "stderr", "stdin"):
        monkeypatch.setattr(sys, name, None)

    wincon.ensure_streams()

    for name in ("stdout", "stderr", "stdin"):
        assert getattr(sys, name) is not None, f"sys.{name} left as None"

    # and the result is actually usable
    sys.stdout.write("discarded")
    sys.stdout.flush()


def test_ensure_streams_leaves_working_streams_alone(monkeypatch):
    from yazses.system import wincon

    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    wincon.ensure_streams()
    assert sys.stdout is buf


@pytest.mark.skipif(sys.platform == "win32", reason="tests the non-Windows path")
def test_attach_parent_console_is_a_noop_off_windows():
    from yazses.system import wincon

    assert wincon._attach_parent_console() is False
