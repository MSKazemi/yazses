"""Barge-in must cancel a read-back that has been requested but not yet begun.

Read-back is spoken on a background thread so playback never blocks the hotkey
loop, and a new hold cancels it -- ``_on_hold_start`` calls ``tts.cancel()`` "so
the user's speech is never recorded over the spoken transcript".

Between those two facts sits the window this file exists for. ``_speak_readback``
spawns the thread and returns; the thread does not necessarily run a single
bytecode before the hotkey thread continues. A user who releases the key and
immediately holds again -- the ordinary way to dictate a second sentence -- fires
the barge-in while the read-back thread is still unscheduled. The cancel then
lands on a backend that has not started, and the very first thing the worker did
on waking was clear the flag, so the previous transcript was spoken over the new
dictation and the barge-in silently did nothing.

That is not a rare interleaving. The hotkey thread holds the GIL through the rest
of ``_on_hold_end`` and into ``_on_hold_start``, and a freshly started thread
typically waits for a switch interval, so on a quick re-hold losing the cancel is
the *likely* outcome rather than the unlucky one.

The ordering is therefore made explicit rather than left to the scheduler: a
read-back claims a sequence number when it is requested, ``_on_hold_start`` bumps
that number under the same lock, and the worker takes the claim -- and clears the
backend's barge-in flag -- inside one critical section. A cancel issued before the
worker's section makes the numbers disagree and the utterance is dropped; a cancel
issued after it sets a flag the worker has already stopped being able to clear.
There is no window between the two.
"""
from __future__ import annotations

from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.platform import get_platform


class _FakeTts:
    """A backend faithful to the real one on the single point under test.

    ``KokoroTtsBackend.speak`` clears the barge-in flag for a caller that did not
    claim the utterance first, because a caller who never orders its own cancels
    would otherwise be silenced permanently by one barge-in. That self-healing
    clear is modelled here, and it is what makes the assertions below falsifying: a
    daemon that spawns the worker without claiming anything reaches ``speak`` with
    the cancel already wiped, and speaks.
    """

    name = "fake"

    def __init__(self) -> None:
        self.spoken: list[str] = []
        self.cancels = 0
        self.cancelled = False
        self.claimed = False

    def begin(self) -> None:
        self.claimed = True
        self.cancelled = False

    def speak(self, text: str) -> None:
        if not self.claimed:
            self.cancelled = False
        self.claimed = False
        if self.cancelled:
            return
        self.spoken.append(text)

    def synthesize(self, text):
        return iter(())

    def cancel(self) -> None:
        self.cancels += 1
        self.cancelled = True


class _DeferredThread:
    """A `threading.Thread` stand-in that runs nothing until the test says so.

    The bug is about a worker that has not been scheduled yet, so the test must be
    able to hold it there. Deferring the target is exactly that state, made
    deterministic instead of raced for.
    """

    pending: list = []

    def __init__(self, target=None, daemon=None, name=None, **kwargs) -> None:
        self._target = target

    def start(self) -> None:
        _DeferredThread.pending.append(self._target)


def _daemon(monkeypatch):
    cfg = Config()
    cfg.tts.enabled = True
    cfg.accessibility.read_back = "final"
    d = Daemon(config=cfg, platform=get_platform())
    tts = _FakeTts()
    d._tts = tts
    d._padding_buffer = None
    # `_on_hold_start` probes the focused window off-thread; the answer is irrelevant
    # here and shelling out to xdotool from a unit test is not.
    monkeypatch.setattr(d, "_detect_target_async", lambda: None)
    _DeferredThread.pending = []
    monkeypatch.setattr("yazses.core.daemon.threading.Thread", _DeferredThread)
    return d, tts


def test_a_barge_in_before_the_worker_runs_cancels_the_readback(monkeypatch) -> None:
    d, tts = _daemon(monkeypatch)

    d._speak_readback("the previous sentence")
    assert _DeferredThread.pending, "read-back did not start a worker"

    # The user holds the key again before the worker has run a single bytecode.
    d._on_hold_start(0)
    assert tts.cancels == 1, "barge-in did not reach the backend"

    # Only now does the worker get scheduled.
    _DeferredThread.pending[0]()

    assert tts.spoken == [], (
        "a read-back cancelled before it started was spoken anyway, over the "
        "dictation the user had already begun"
    )


def test_a_readback_requested_after_the_barge_in_is_still_spoken(monkeypatch) -> None:
    """The gate must drop the utterance the cancel was aimed at, and nothing else.

    Without this, dropping every read-back would satisfy the test above -- and
    read-back would never work again after the first barge-in.
    """
    d, tts = _daemon(monkeypatch)

    d._on_hold_start(0)          # an earlier burst cancelled whatever was playing
    d._speak_readback("the sentence just dictated")
    _DeferredThread.pending[0]()

    assert tts.spoken == ["the sentence just dictated"]


def test_the_worker_runs_normally_when_no_barge_in_arrives(monkeypatch) -> None:
    d, tts = _daemon(monkeypatch)
    d._speak_readback("hello world")
    _DeferredThread.pending[0]()
    assert tts.spoken == ["hello world"]
