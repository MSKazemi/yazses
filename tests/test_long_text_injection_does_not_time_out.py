"""QA-004: a backend handed a very long text, or a long key run, must not time out.

A timeout here is not a slow success. `subprocess.run` raises `TimeoutExpired`
*after* the tool has already sent part of the keys, `LinuxInjector` reads that as a
broken backend and replays the whole request through `ClipboardInjector`, and the
streaming commit's selection then runs past the partial text into text the user
kept (#153). So every call must be given a timeout that covers the work it asks for.

#153 fixed that for `XdotoolInjector` and noted that "`inject/xdotool.py` and
`inject/ydotool.py` ... have repeatedly drifted". They had again: `YdotoolInjector`
scaled the timeout of `type` but gave `key` -- which is what the streaming commit
(`["shift+Left"] * N`) and cancel (`inject_backspaces(N)`) use -- a fixed 10 s, and
so did every key path of the clipboard fallback. At ydotool's default 12 ms per
event, `shift+Left` is four events, so a fixed 10 s expires at about 208 characters
of partial text.

Each test drives the real argv through a fake `subprocess.run` that charges the
tool's nominal per-event cost and raises `TimeoutExpired` when that exceeds the
timeout the caller passed -- the only thing a real tool would do differently is
take the time.
"""

from __future__ import annotations

import subprocess

import pytest

from yazses.inject import ydotool as yd
from yazses.inject.clipboard import ClipboardInjector
from yazses.inject.streaming import StreamingInjector
from yazses.inject.xdotool import XdotoolInjector
from yazses.inject.ydotool import YdotoolInjector, ydotool_key_timeout

# The tools' own defaults: ydotool `key` waits 12 ms per event (1.x `-d`, 0.1.x
# `--key-delay`); `YdotoolInjector` types at 6 ms delay + 6 ms hold; xdotool sleeps
# 12 ms per keystroke for both `type --delay 12` and `key`.
_YDOTOOL_KEY_EVENT_S = 0.012
_YDOTOOL_TYPE_CHAR_S = 0.012
_XDOTOOL_KEYSTROKE_S = 0.012

LONG = 2000  # characters: a long hold, well past every fixed-timeout wall below


def _ydotool_key_events(argv: list[str]) -> int:
    """Events a `ydotool key` argv emits, in either dialect."""
    tokens = [a for a in argv[2:] if not a.startswith("-")]
    if "--key-delay" in argv or "-d" in argv:
        tokens = tokens[1:]  # the delay value itself
    if all(":" in t for t in tokens):  # 1.x: one `<code>:<state>` token per event
        return len(tokens)
    # 0.1.x: one `a+b+c` token per combo, a press and a release of each key in it.
    return sum(2 * len(t.split("+")) for t in tokens)


def _cost_seconds(argv: list[str]) -> float:
    tool, verb = argv[0], argv[1] if len(argv) > 1 else ""
    if tool == "ydotool" and verb == "key":
        return _ydotool_key_events(argv) * _YDOTOOL_KEY_EVENT_S
    if tool == "ydotool" and verb == "type":
        return len(argv[argv.index("--") + 1]) * _YDOTOOL_TYPE_CHAR_S
    if tool == "xdotool" and verb == "type":
        return len(argv[argv.index("--") + 1]) * _XDOTOOL_KEYSTROKE_S
    if tool == "xdotool" and verb == "key":
        args = [a for a in argv[2:] if a != "--clearmodifiers"]
        if args[:1] == ["--repeat"]:
            return int(args[1]) * len(args[2:]) * _XDOTOOL_KEYSTROKE_S
        return len(args) * _XDOTOOL_KEYSTROKE_S
    return 0.0  # wl-copy, xclip: not keystroke-bound


@pytest.fixture
def clock(monkeypatch):
    """Replace `subprocess.run` with a model that times out the way a real tool does."""
    calls: list[tuple[list[str], float, float | None]] = []

    def run(cmd, check=False, timeout=None, **_kw):
        cost = _cost_seconds(list(cmd))
        calls.append((list(cmd), cost, timeout))
        if timeout is not None and cost > timeout:
            raise subprocess.TimeoutExpired(cmd, timeout)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr("yazses.inject.clipboard.time.sleep", lambda _s: None)
    return calls


@pytest.fixture(params=[yd.DIALECT_V1, yd.DIALECT_V0])
def dialect(request):
    yd.set_ydotool_dialect(request.param)
    yield request.param
    yd.set_ydotool_dialect(yd.DIALECT_V1)  # what the suite-wide conftest pins


# ---- YdotoolInjector: the Wayland primary ------------------------------------


def test_ydotool_long_type_does_not_time_out(clock, dialect):
    """Pins the timeout `type` already had (`10 + len * 0.03`)."""
    YdotoolInjector().inject("a" * LONG)


def test_ydotool_streaming_commit_selection_does_not_time_out(clock, dialect):
    """The streaming commit's `shift+Left x N` -- four events per character."""
    YdotoolInjector().inject_key_sequence(["shift+Left"] * LONG)


def test_ydotool_streaming_cancel_backspaces_do_not_time_out(clock, dialect):
    YdotoolInjector().inject_backspaces(LONG)


def test_ydotool_short_sequences_keep_the_old_ten_second_floor(clock):
    YdotoolInjector().inject_key_sequence(["ctrl+v"])
    assert clock[-1][2] == pytest.approx(10.0, abs=0.5)


def test_streaming_commit_on_ydotool_end_to_end(clock, dialect):
    """A long dictation's partials, then the commit -- nothing raises."""
    stream = StreamingInjector(YdotoolInjector())
    for i in range(50):
        stream.inject_partial(f"partial number {i} of a long dictation. ")
    assert stream.chars_injected > 1500
    stream.commit("the final text " * 120)


# ---- ClipboardInjector: the fallback that replays a failed request ----------


@pytest.fixture
def wayland_with_ydotool(monkeypatch):
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setattr("yazses.inject.clipboard._ydotool_ready", lambda: True)


@pytest.fixture
def x11(monkeypatch):
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)


def test_clipboard_wayland_key_sequence_does_not_time_out(clock, dialect, wayland_with_ydotool):
    ClipboardInjector().inject_key_sequence(["shift+Left"] * LONG)


def test_clipboard_wayland_backspaces_do_not_time_out(clock, dialect, wayland_with_ydotool):
    ClipboardInjector().inject_backspaces(LONG)


def test_clipboard_x11_key_sequence_does_not_time_out(clock, x11):
    ClipboardInjector().inject_key_sequence(["shift+Left"] * LONG)


def test_clipboard_x11_backspaces_do_not_time_out(clock, x11):
    ClipboardInjector().inject_backspaces(LONG)


def test_clipboard_long_paste_is_not_keystroke_bound(clock, x11):
    """A paste is one Ctrl+V however long the text -- the reason it is the fallback."""
    ClipboardInjector().inject("a" * 20 * LONG)


# ---- XdotoolInjector: pinned by #153, repeated here so the family is complete --


def test_xdotool_long_text_and_keys_do_not_time_out(clock):
    inj = XdotoolInjector()
    inj.inject("a" * LONG)
    inj.inject_key_sequence(["shift+Left"] * LONG)
    inj.inject_backspaces(LONG)


# ---- the budget itself ------------------------------------------------------


def test_key_timeout_counts_every_key_of_a_combo():
    one_key = ydotool_key_timeout(["KEY_BACKSPACE"] * 100)
    two_keys = ydotool_key_timeout(["shift+Left"] * 100)
    assert two_keys - 10.0 == pytest.approx(2 * (one_key - 10.0))


def test_key_timeout_follows_an_explicit_key_delay():
    slow = ydotool_key_timeout(["ctrl+v"] * 100, key_delay_ms=40)
    default = ydotool_key_timeout(["ctrl+v"] * 100)
    assert slow > default
    assert ydotool_key_timeout([], key_delay_ms=-5) == pytest.approx(10.0)
