"""`yazses doctor > log.txt` must not die on Windows.

Python encodes stdout with the *locale* encoding whenever it is not attached to a
console — a redirect, a pipe, a CI capture, `yazses report`. On Windows that is the ANSI
code page. Measured on a real Windows Server 2022 host: `sys.stdout.encoding` is
`cp1252`, and three commands aborted mid-report with

    UnicodeEncodeError: 'charmap' codec can't encode characters ...

    CRASH  rc=1  yazses doctor
    CRASH  rc=1  yazses features
    CRASH  rc=1  yazses quickstart

They are exactly the three commands somebody runs when something is already wrong, and
then pastes into an issue. The characters are not decoration in some rare branch: `→`
appears 437 times across 166 modules — it is the arrow in nearly every "fix it like
this" line — plus `⚠`, the `─` that frames a panel, and the `●`/`★` markers
`yazses audio devices` uses for the default and pinned microphone.

Even where cp1252 *can* encode a character the result is wrong: an em dash goes out as
the single byte 0x97, which a console on code page 437 draws as `ù`. Also observed on
that host, piping doctor through findstr.

None of this reproduces on a normal Linux or macOS install, where the locale is UTF-8,
so the tests below supply the encoding rather than the platform.
"""

from __future__ import annotations

import io
import sys

import pytest

from yazses.system.streams import _PRINTS, ensure_printable_streams


class _Stream:
    """A text stream that reports an encoding and records reconfiguration."""

    def __init__(self, encoding: str) -> None:
        self.encoding = encoding
        self.calls: list[dict] = []

    def reconfigure(self, **kwargs) -> None:
        self.calls.append(kwargs)
        self.encoding = kwargs.get("encoding", self.encoding)


class _Rigid:
    """A stream with no `reconfigure` at all — an older or wrapped file object."""

    def __init__(self, encoding: str) -> None:
        self.encoding = encoding


def test_the_characters_the_cli_prints_really_do_break_cp1252() -> None:
    """Anchors the premise. If this ever stops raising, the rest is theatre."""
    with pytest.raises(UnicodeEncodeError):
        _PRINTS.encode("cp1252")


@pytest.mark.parametrize("encoding", ["cp1252", "ascii", "cp437", "latin-1"])
def test_a_stream_that_cannot_carry_them_is_switched_to_utf8(monkeypatch, encoding) -> None:
    out, err = _Stream(encoding), _Stream(encoding)
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)

    ensure_printable_streams()

    for stream in (out, err):
        assert stream.calls, f"{encoding} stream was left unable to print the CLI's output"
        assert stream.calls[-1]["encoding"] == "utf-8"


def test_it_degrades_rather_than_aborting_on_something_unmappable(monkeypatch) -> None:
    """`errors="replace"` is the half that keeps a half-written report readable.

    A diagnostic command that meets one character it cannot encode should print `?` and
    carry on, never abort in the middle of the output the user is trying to send.
    """
    out = _Stream("cp1252")
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", _Stream("cp1252"))

    ensure_printable_streams()

    assert out.calls[-1].get("errors") == "replace"


@pytest.mark.parametrize("encoding", ["utf-8", "UTF-8", "utf8"])
def test_a_stream_that_is_already_fine_is_left_completely_alone(monkeypatch, encoding) -> None:
    """Every Linux and macOS install lands here, and some output is byte-exact.

    `yazses vocab export` has a round-trip test; reconfiguring its stream as a side
    effect of a Windows fix would be a regression nothing else would notice.
    """
    out, err = _Stream(encoding), _Stream(encoding)
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)

    ensure_printable_streams()

    assert out.calls == [] and err.calls == []


def test_a_missing_stream_is_not_an_error(monkeypatch) -> None:
    """PyInstaller's windowed build sets all three to None — the case streams.py exists for."""
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    ensure_printable_streams()  # must not raise


def test_a_stream_that_cannot_be_reconfigured_is_not_an_error(monkeypatch) -> None:
    monkeypatch.setattr(sys, "stdout", _Rigid("cp1252"))
    monkeypatch.setattr(sys, "stderr", _Rigid("cp1252"))
    ensure_printable_streams()  # must not raise


def test_a_reconfigure_that_refuses_is_swallowed(monkeypatch) -> None:
    """A detached or already-closed stream raises from reconfigure itself."""

    class _Hostile(_Stream):
        def reconfigure(self, **kwargs):
            raise ValueError("underlying buffer has been detached")

    monkeypatch.setattr(sys, "stdout", _Hostile("cp1252"))
    monkeypatch.setattr(sys, "stderr", _Hostile("cp1252"))
    ensure_printable_streams()  # must not raise


def test_an_unknown_encoding_name_is_treated_as_unusable(monkeypatch) -> None:
    """`str.encode` raises LookupError, not UnicodeEncodeError, for a bogus codec."""
    out = _Stream("not-a-real-codec")
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", _Stream("not-a-real-codec"))
    ensure_printable_streams()
    assert out.calls, "an encoding nothing can look up must not read as 'already fine'"


def test_a_real_wrapper_stops_raising_once_it_is_applied(monkeypatch) -> None:
    """End to end on a genuine TextIOWrapper, not the stub above.

    Reproduces the Windows condition exactly — a byte sink wrapped in cp1252 — and shows
    the same write failing before and succeeding after.
    """
    raw = io.BytesIO()
    wrapper = io.TextIOWrapper(raw, encoding="cp1252", newline="")
    monkeypatch.setattr(sys, "stdout", wrapper)
    monkeypatch.setattr(sys, "stderr", io.TextIOWrapper(io.BytesIO(), encoding="cp1252"))

    with pytest.raises(UnicodeEncodeError):
        wrapper.write(_PRINTS)
        wrapper.flush()

    ensure_printable_streams()

    sys.stdout.write(_PRINTS)
    sys.stdout.flush()
    assert _PRINTS.encode("utf-8") in raw.getvalue()


def test_the_cli_entry_point_applies_it_before_anything_prints() -> None:
    """Guards the guard: every test above calls the function directly, so all of them
    would pass on a CLI that never calls it — which was the state that shipped."""
    import ast
    import inspect

    from yazses import cli as cli_mod

    body = ast.parse(inspect.getsource(cli_mod.main))
    called = [
        n.func.id for n in ast.walk(body)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    ]
    assert "ensure_printable_streams" in called, "cli.main never fixes the output streams"
    assert called.index("ensure_printable_streams") < called.index("app"), (
        "the streams are fixed after the app has already run and printed"
    )
