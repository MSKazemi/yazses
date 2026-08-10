"""Streaming must never type after commit, and must never time out mid-correction.

Both defects here produced the same user-visible damage (issue #153): a burst of
repeated characters at the end of a long dictation, followed by a correction pass
that deleted text the user wanted to keep.

1. ``XdotoolInjector`` used a **fixed** ``timeout=10``. At 12 ms per keystroke that
   expires around 833 characters — *after* xdotool has already typed part of the
   text — so the caller sees a failure for work that partly happened, falls back
   to the clipboard, and the text lands twice. ``YdotoolInjector`` scaled its
   timeout for exactly this reason; the X11 path never got the fix.

2. ``StreamingInjector`` had no synchronisation. ``inject_partial`` runs on the
   daemon's poll thread while ``commit`` runs on hold-release, and the daemon's
   ``join(timeout=1.0)`` cannot outwait an injection allowed to take ten times
   that. A partial could therefore land after ``commit`` had read the character
   count, making ``shift+Left × N`` select a span that no longer matched what was
   on screen.
"""

from __future__ import annotations

import threading

import pytest

from yazses.inject.streaming import StreamingInjector
from yazses.inject.xdotool import XdotoolInjector, _timeout_for

# ---- 1. the timeout must scale with the work asked of xdotool ---------------


def _run_recorder(calls):
    def run(cmd, **kw):
        calls.append((cmd, kw.get("timeout")))
        return None

    return run


def test_type_timeout_scales_with_text_length(monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr("yazses.inject.xdotool.subprocess.run", _run_recorder(calls))
    inj = XdotoolInjector()
    inj.inject("x" * 20)
    inj.inject("x" * 2000)
    short, long_ = calls[0][1], calls[1][1]
    assert long_ > short, "a long dictation must get a longer timeout"
    # The regression: 2000 chars at 12 ms is ~24 s of typing, so a fixed 10 s
    # timeout would fire mid-type and the text would be injected twice.
    assert long_ >= 10 + 2000 * 0.03


def test_key_sequence_timeout_scales_with_key_count(monkeypatch):
    """The streaming commit sends one shift+Left per character — the selection
    pass hits the same wall as the typing pass, and hits it on the same burst."""
    calls: list[tuple] = []
    monkeypatch.setattr("yazses.inject.xdotool.subprocess.run", _run_recorder(calls))
    XdotoolInjector().inject_key_sequence(["shift+Left"] * 2000)
    assert calls[0][1] >= 10 + 2000 * 0.03


def test_backspace_timeout_scales_with_count(monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr("yazses.inject.xdotool.subprocess.run", _run_recorder(calls))
    XdotoolInjector().inject_backspaces(2000)
    assert calls[0][1] >= 10 + 2000 * 0.03


def test_timeout_never_shrinks_below_the_base():
    assert _timeout_for(0) == 10.0
    assert _timeout_for(-5) == 10.0  # never negative, whatever the caller passes


def test_a_repeated_key_collapses_to_one_repeat_spec(monkeypatch):
    """`["shift+Left"] * 900` as 900 argv entries is how the commit used to go
    out. One --repeat spec sends the same keystrokes without the argv bulk."""
    calls: list[tuple] = []
    monkeypatch.setattr("yazses.inject.xdotool.subprocess.run", _run_recorder(calls))
    XdotoolInjector().inject_key_sequence(["shift+Left"] * 900)
    cmd = calls[0][0]
    assert "--repeat" in cmd and "900" in cmd
    assert cmd.count("shift+Left") == 1


def test_mixed_keys_are_still_sent_verbatim(monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr("yazses.inject.xdotool.subprocess.run", _run_recorder(calls))
    XdotoolInjector().inject_key_sequence(["ctrl+a", "BackSpace"])
    cmd = calls[0][0]
    assert "--repeat" not in cmd
    assert cmd[-2:] == ["ctrl+a", "BackSpace"]


def test_single_key_is_not_collapsed(monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr("yazses.inject.xdotool.subprocess.run", _run_recorder(calls))
    XdotoolInjector().inject_key_sequence(["Return"])
    assert "--repeat" not in calls[0][0]


# ---- 2. a partial must never land after the commit --------------------------


class _Recorder:
    """An injector that records the exact order of operations."""

    def __init__(self) -> None:
        self.ops: list[tuple] = []

    def inject(self, text: str) -> None:
        self.ops.append(("type", text))

    def inject_key_sequence(self, keys: list[str]) -> None:
        self.ops.append(("keys", len(keys)))

    def inject_backspaces(self, count: int) -> None:
        self.ops.append(("bs", count))


def test_partial_after_commit_is_dropped():
    rec = _Recorder()
    si = StreamingInjector(rec)
    si.inject_partial("hel")
    si.commit("hello world")
    si.inject_partial("lo")  # the late partial from the still-alive poll thread
    assert rec.ops == [("type", "hel"), ("keys", 3), ("type", "hello world")], (
        "a partial typed after commit appends stale text behind the final text"
    )
    assert si.sealed is True


def test_partial_after_cancel_is_dropped():
    rec = _Recorder()
    si = StreamingInjector(rec)
    si.inject_partial("hel")
    si.cancel()
    si.inject_partial("lo")
    assert rec.ops == [("type", "hel"), ("bs", 3)]


def test_commit_uses_the_count_that_was_actually_typed():
    rec = _Recorder()
    si = StreamingInjector(rec)
    si.inject_partial("hello ")
    si.inject_partial("world")
    si.commit("Hello, world!")
    assert ("keys", 11) in rec.ops  # 6 + 5, not 0 and not 13


def test_reset_unseals_for_reuse():
    rec = _Recorder()
    si = StreamingInjector(rec)
    si.inject_partial("a")
    si.commit("A")
    si.reset()
    si.inject_partial("b")
    assert ("type", "b") in rec.ops
    assert si.chars_injected == 1


def test_commit_waits_for_an_in_flight_partial():
    """The real race: hold-release fires while a partial is mid-injection.

    ``commit`` must not compute its selection until that injection has finished,
    otherwise it selects a span shorter than what is on screen and the leftover
    characters survive while real text is eaten.
    """
    order: list[str] = []
    started = threading.Event()
    release = threading.Event()

    class _SlowInjector:
        def inject(self, text: str) -> None:
            if text == "slow":
                started.set()
                release.wait(timeout=5)
                order.append("partial-done")
            else:
                order.append(f"type:{text}")

        def inject_key_sequence(self, keys: list[str]) -> None:
            order.append(f"keys:{len(keys)}")

        def inject_backspaces(self, count: int) -> None:  # pragma: no cover
            order.append(f"bs:{count}")

    si = StreamingInjector(_SlowInjector())
    t = threading.Thread(target=si.inject_partial, args=("slow",), daemon=True)
    t.start()
    assert started.wait(timeout=5), "the slow partial never started"

    committed = threading.Event()

    def do_commit():
        si.commit("final")
        committed.set()

    c = threading.Thread(target=do_commit, daemon=True)
    c.start()
    # commit must be blocked on the lock while the partial is still typing
    assert not committed.wait(timeout=0.3), "commit ran during an in-flight partial"

    release.set()
    t.join(timeout=5)
    assert committed.wait(timeout=5), "commit never completed"

    assert order[0] == "partial-done"
    # 4 = len("slow"): the count includes the partial that was in flight.
    assert order[1] == "keys:4"
    assert order[2] == "type:final"


def test_concurrent_partials_keep_an_exact_count():
    """Whatever the interleaving, the count must equal the characters typed —
    it is the number of shift+Lefts that will later delete them."""
    rec = _Recorder()
    si = StreamingInjector(rec)
    threads = [
        threading.Thread(target=si.inject_partial, args=("abcde",), daemon=True)
        for _ in range(20)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)
    assert si.chars_injected == 100
    assert sum(len(text) for op, text in rec.ops if op == "type") == 100


@pytest.mark.parametrize("finisher", ["commit", "cancel"])
def test_no_double_correction_if_called_twice(finisher):
    """A second commit/cancel must not send another correction — the count is
    already zero, and re-selecting would eat text that is not ours."""
    rec = _Recorder()
    si = StreamingInjector(rec)
    si.inject_partial("hello")
    getattr(si, finisher)("x") if finisher == "commit" else si.cancel()
    corrections_after_first = [o for o in rec.ops if o[0] in ("keys", "bs")]
    getattr(si, finisher)("x") if finisher == "commit" else si.cancel()
    corrections_after_second = [o for o in rec.ops if o[0] in ("keys", "bs")]
    assert corrections_after_first == corrections_after_second
