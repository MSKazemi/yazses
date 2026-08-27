"""Earcon feedback wired into the daemon (ADR-v2-096, via the accessibility study).

The tone grammar and the synth are pure and covered elsewhere. What is tested here is
the playback layer, and every test is about a way it could damage dictation rather than
about how it sounds.

The reasoning: this is a *courtesy* on the hot path. `_on_hold_start` fires when the key
goes down, and every millisecond before capture begins is speech that is lost. A cue that
blocks, raises, or stacks up is strictly worse than no cue at all — so the failure modes
are the specification.
"""

from __future__ import annotations

import threading
import time
from dataclasses import replace

import pytest

from tests.conftest import sounddevice_or_skip
from yazses.config import Config, EarconConfig
from yazses.core.daemon import Daemon
from yazses.earcon.play import EarconPlayer
from yazses.platform import get_platform


@pytest.fixture
def audio():
    """Skip when sounddevice cannot be imported, rather than fail.

    The six tests below patch `sounddevice.play`, and `mock.patch` has to import the
    module to reach the attribute. On a host with no audio system that import raises
    `PortAudioError` from `Pa_Initialize()` -- not something these tests are about,
    and not something the earcon player would ever do, since `earcon/play.py` imports
    sounddevice inside the function it plays from.
    """
    return sounddevice_or_skip()


# ---- it must never get in the way ------------------------------------------


def test_disabled_player_does_nothing_at_all(mocker, audio):
    """The default. It must not import an audio library, let alone open a device."""
    played = mocker.patch("sounddevice.play")
    EarconPlayer(enabled=False).play("recording_start")
    played.assert_not_called()


def test_a_broken_audio_device_never_reaches_the_caller(mocker, audio):
    """No speakers, a busy device, a container, an SSH session — all ordinary, none of
    them may interrupt someone's dictation."""
    mocker.patch("sounddevice.play", side_effect=OSError("no such device"))
    player = EarconPlayer(enabled=True)
    player.play("recording_start")          # must not raise
    _settle()


def test_playback_does_not_block_the_caller(mocker, audio):
    """`_on_hold_start` is the hot path: the user has pressed the key and is about to
    speak. A blocking cue would swallow the first word."""
    started = threading.Event()

    def _slow(*_a, **_k):
        started.set()
        time.sleep(1.0)

    mocker.patch("sounddevice.play", side_effect=_slow)
    player = EarconPlayer(enabled=True)

    began = time.monotonic()
    player.play("recording_start")
    elapsed = time.monotonic() - began

    assert elapsed < 0.2, f"play() blocked for {elapsed:.2f}s"
    assert started.wait(timeout=2.0), "playback never actually started"
    _settle()   # do not leave a thread to call into the next test's mock


def test_a_second_cue_is_dropped_rather_than_queued(mocker, audio):
    """Hold, release, hold again in quick succession must not stack three motifs.

    Dropping is deliberate: an earcon that arrives late describes a state the daemon has
    already left, which is worse than silence.

    Synchronised with events rather than sleeps. The first draft slept 50 ms and hoped
    the playback thread had started by then; it passed alone and failed about one run in
    three under load, which is a flaky test — a worse defect than the one it looks for,
    because it trains people to re-run the suite.
    """
    _settle()   # no thread from an earlier test may be counted as one of ours
    calls = []
    playing = threading.Event()
    release = threading.Event()

    def _blocking(*_a, **_k):
        calls.append(1)
        playing.set()
        release.wait(timeout=2.0)

    mocker.patch("sounddevice.play", side_effect=_blocking)
    player = EarconPlayer(enabled=True)

    player.play("recording_start")
    assert playing.wait(timeout=2.0), "the first cue never started"

    # Now that one is definitely sounding, these two must be dropped, not queued.
    player.play("recording_stop")
    player.play("recording_start")

    release.set()
    _settle()
    assert len(calls) == 1, f"{len(calls)} cues played concurrently; expected 1"


def test_the_slot_is_released_after_a_failure(mocker, audio):
    """A failed cue must not wedge the player silent forever."""
    mocker.patch("sounddevice.play", side_effect=OSError("boom"))
    player = EarconPlayer(enabled=True)
    player.play("recording_start")
    _settle()
    assert player._busy.acquire(blocking=False), "the lock was never released"
    player._busy.release()


def test_an_unknown_event_falls_back_to_the_idle_motif(mocker, audio):
    """`earcon_for` never returns nothing — an unrecognised event gets the idle tone.

    That is the pure layer's documented contract and the right one for it: a caller
    asking for a cue should get *a* cue rather than silence it cannot detect. Asserted
    here so the player is not later "fixed" to swallow it, which would make a typo'd
    event name silently undiagnosable.
    """
    played = mocker.patch("sounddevice.play")
    EarconPlayer(enabled=True).play("no_such_event")
    _settle()
    played.assert_called_once()


# ---- it is actually reached from the dictation path ------------------------


def test_the_daemon_builds_a_player_that_is_off_by_default():
    d = Daemon(config=Config(), platform=get_platform())
    assert d._earcon.enabled is False


def test_the_daemon_builds_an_enabled_player_when_configured():
    cfg = replace(Config(), earcon=EarconConfig(enabled=True))
    assert Daemon(config=cfg, platform=get_platform())._earcon.enabled is True


@pytest.mark.parametrize(
    "method, expected",
    [("_on_hold_start", "recording_start"), ("_on_hold_end", "recording_stop")],
)
def test_the_hold_boundaries_each_play_their_cue(method, expected):
    """A player nothing calls would pass every test above.

    Read the call sites out of the source: the alternative is driving a real hold, which
    needs a microphone and a model.
    """
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(getattr(Daemon, method))))
    events = [
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "play"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    ]
    assert expected in events, f"{method} never plays {expected!r} (found {events})"


def test_a_discarded_burst_is_announced():
    """The case that matters most without a screen: you spoke, and nothing is coming.

    Silence here is indistinguishable from a slow transcription, so the user waits for
    text that will never arrive.
    """
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(Daemon._on_hold_end)))
    events = [
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "play"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    ]
    assert "error" in events, (
        "a silent-audio discard plays no cue, so an eyes-free user cannot tell it "
        "apart from a slow decode"
    )


def _settle(seconds: float = 2.5) -> None:
    """Wait until no earcon playback thread is alive.

    Threads are matched **by name**, not by counting them. The first version compared
    `threading.active_count()` against a constant, which is wrong in a suite: pytest and
    the daemon fixtures have threads of their own, so the count never reached the
    expected value and this returned only on its timeout.

    That mattered more than it sounds. A playback thread left running from an earlier
    test calls `sd.play` inside the *next* test's patch window and is counted as that
    test's call — which is what made the "second cue is dropped" test fail about half
    the time while passing in isolation.
    """
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not [t for t in threading.enumerate() if t.name == "earcon" and t.is_alive()]:
            return
        time.sleep(0.01)
