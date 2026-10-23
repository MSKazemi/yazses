"""The device monitor re-scans while a hands-free level stream holds the microphone.

The bug (reported 2026-10-22 by the agents that wired the features): Vocal Morse keeps a
level stream open all session while it listens for its entry hum -- the default whenever
`[morsevox]` is on -- and the Mouth-Sound Switch and the Vocal Joystick do the same while
armed. `Daemon._audio_idle` is False while any of them is open, so that a PortAudio re-init
cannot close the stream under it, and `DeviceMonitor.poll_once` skipped every poll that was
not idle. With Morse on, the monitor therefore never polled: an unplugged mic, a new default
or a Bluetooth headset switch went unnoticed for the whole session.

Pinned here, with fake streams, a fake backend and a fake clock (no audio library, no
thread, no sleep):

* the pure policy `plan_device_poll` -- every branch;
* `DeviceMonitor` coordinates instead of waiting: it closes the open streams, re-inits, and
  reopens them; PortAudio is **never** re-initialised while a stream is open or while
  dictation records; a user mid-gesture defers the cycle, but a frozen (dead) stream does not;
* the three real runners: `release` closes, `reacquire` reopens -- and never reopens what a
  pause, the gate or a fault closed in between.
"""
from __future__ import annotations

import types
from dataclasses import dataclass

import numpy as np
import pytest

from tests.pointer_fake import FakePointerSink
from tests.synthetic_voice import PETERSON_BARNEY_MALE, SR, vowel
from yazses.audio.device_monitor import (
    CYCLE,
    ENGAGED_AUDIO_FRESH_S,
    ENGAGED_DEFER_MAX_S,
    LEVEL_STREAM_RESCAN_S,
    PEEK,
    RESCAN,
    SKIP,
    DeviceMonitor,
    audio_is_live,
    plan_device_poll,
)


class Clock:
    """A monotonic clock moved by hand."""

    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


# --------------------------------------------------------------------------- #
# The pure policy
# --------------------------------------------------------------------------- #
def _plan(**kw) -> str:
    base = dict(
        recording=False, streams_open=True, engaged=False, now=10.0, last_rescan_at=0.0,
        engaged_since=None, rebind_pending=False, can_peek=True,
        rescan_every_s=30.0, max_defer_s=600.0,
    )
    base.update(kw)
    return plan_device_poll(**base)


@pytest.mark.parametrize("streams_open", [False, True])
@pytest.mark.parametrize("rebind_pending", [False, True])
def test_a_recording_in_flight_touches_nothing_whatever_else_is_true(streams_open, rebind_pending):
    assert _plan(recording=True, streams_open=streams_open, rebind_pending=rebind_pending,
                 now=1000.0) == SKIP


def test_with_no_level_stream_open_it_is_the_old_rescan():
    assert _plan(streams_open=False) == RESCAN


def test_between_rescans_it_only_peeks():
    assert _plan(now=29.9) == PEEK


def test_between_rescans_without_a_peek_reader_it_waits():
    assert _plan(now=29.9, can_peek=False) == SKIP


def test_a_due_rescan_cycles_the_streams():
    assert _plan(now=30.0) == CYCLE


def test_a_change_seen_by_a_peek_makes_the_cycle_due_at_once():
    assert _plan(now=1.0, rebind_pending=True) == CYCLE


def test_a_user_mid_gesture_defers_the_cycle():
    assert _plan(now=31.0, engaged=True, engaged_since=20.0) == PEEK
    assert _plan(now=31.0, engaged=True, engaged_since=20.0, can_peek=False) == SKIP
    assert _plan(now=1.0, rebind_pending=True, engaged=True, engaged_since=0.5) == PEEK


def test_an_engagement_that_never_ends_defers_only_up_to_the_backstop():
    assert _plan(now=619.9, engaged=True, engaged_since=20.0) == PEEK
    assert _plan(now=620.0, engaged=True, engaged_since=20.0) == CYCLE


def test_the_shipped_constants_keep_their_order():
    # A cycle is rarer than a poll, the backstop far rarer than a cycle, and "fresh" audio
    # is a couple of seconds -- shorter than any rescan, longer than any audio block.
    assert 3.0 < LEVEL_STREAM_RESCAN_S < ENGAGED_DEFER_MAX_S
    assert 0.5 <= ENGAGED_AUDIO_FRESH_S < LEVEL_STREAM_RESCAN_S


def test_audio_is_live_only_within_the_window():
    assert audio_is_live(None, 5.0) is False
    assert audio_is_live(4.0, 5.0, fresh_s=2.0) is True
    assert audio_is_live(3.0, 5.0, fresh_s=2.0) is True
    assert audio_is_live(2.9, 5.0, fresh_s=2.0) is False
    assert audio_is_live(6.0, 5.0, fresh_s=2.0) is False  # from the future: not evidence


# --------------------------------------------------------------------------- #
# The monitor, with fake streams and a fake backend
# --------------------------------------------------------------------------- #
@dataclass
class World:
    """The backend and the daemon state the monitor sees."""

    device: str = "MicA"
    peek_device: str | None = None  # what a no-re-init read returns; None = "cannot tell"
    recording: bool = False

    def __post_init__(self) -> None:
        self.events: list[str] = []
        self.streams: list[FakeStream] = []
        self.reinits_with_a_stream_open = 0
        self.reinits_while_recording = 0

    def poll(self) -> str:
        """The re-init + read: the one call that must never run under an open stream."""
        if any(s.mic_open for s in self.streams):
            self.reinits_with_a_stream_open += 1
        if self.recording:
            self.reinits_while_recording += 1
        self.events.append("reinit")
        return self.device

    def peek(self) -> str | None:
        self.events.append("peek")
        return self.peek_device

    def is_idle(self) -> bool:
        return not self.recording and not any(s.mic_open for s in self.streams)


class FakeStream:
    """A `LevelStreamOwner`: an open/closed stream with a reopen-only-what-I-closed rule."""

    def __init__(self, world: World, name: str, *, open_: bool = True) -> None:
        self.world = world
        self.name = name
        self.mic_open = open_
        self.engaged = False
        self.hold = False
        self.release_raises = False
        self.reacquire_raises = False
        self.on_release = None
        world.streams.append(self)

    @property
    def mic_engaged(self) -> bool:
        return self.mic_open and self.engaged

    def release_mic_for_rescan(self) -> bool:
        if self.release_raises:
            raise RuntimeError("stuck")
        was_open, self.mic_open = self.mic_open, False
        self.hold = was_open
        self.world.events.append(f"release {self.name}")
        if self.on_release is not None:
            self.on_release()
        return was_open

    def reacquire_mic_after_rescan(self):
        if self.reacquire_raises:
            raise RuntimeError("no device")
        if self.hold:
            self.hold = False
            self.mic_open = True
        self.world.events.append(f"reacquire {self.name}")
        return True, ""

    def user_pause(self) -> None:
        self.mic_open = False
        self.hold = False


def _monitor(world: World, clock: Clock, *, peek: bool = True, fired=None) -> DeviceMonitor:
    fired = fired if fired is not None else []
    return DeviceMonitor(
        poll_fn=world.poll,
        is_idle=world.is_idle,
        on_change=lambda prev, cur: fired.append((prev, cur)),
        level_streams=lambda: list(world.streams),
        recording=lambda: world.recording,
        peek_fn=world.peek if peek else None,
        clock=clock,
    )


def test_the_reported_bug_a_listening_morse_stream_no_longer_blinds_the_monitor():
    """No peek reader (macOS/Windows-like): only a re-init can see the change."""
    world, clock, fired = World(), Clock(), []
    morse = FakeStream(world, "morse")  # open all session, listening for the hum
    monitor = _monitor(world, clock, peek=False, fired=fired)

    for t in (3.0, 6.0, 27.0):  # inside the rescan window: nothing is touched
        clock.t = t
        assert monitor.poll_once() is False
    assert world.events == []

    clock.t = LEVEL_STREAM_RESCAN_S
    assert monitor.poll_once() is False  # the baseline, through a cycle
    assert monitor.last_action == CYCLE
    world.device = "Bluetooth headset"  # the switch nothing used to notice
    clock.t = 2 * LEVEL_STREAM_RESCAN_S
    assert monitor.poll_once() is True
    assert fired == [("MicA", "Bluetooth headset")]
    # Closed, re-initialised, reopened -- in that order, twice.
    assert world.events == ["release morse", "reinit", "reacquire morse"] * 2
    assert world.reinits_with_a_stream_open == 0
    assert morse.mic_open, "the hum listener must be listening again"


def test_a_peek_sees_the_switch_at_once_and_the_next_poll_rebinds_the_streams():
    """PipeWire-like: `wpctl` sees through `default` without a re-init."""
    world, clock, fired = World(peek_device="MicA"), Clock(), []
    morse = FakeStream(world, "morse")
    monitor = _monitor(world, clock, fired=fired)

    clock.t = 3.0
    assert monitor.poll_once() is False and monitor.last_action == PEEK  # baseline
    world.peek_device = world.device = "USB mic"
    clock.t = 6.0
    assert monitor.poll_once() is True  # noticed within one poll, no stream closed
    assert fired == [("MicA", "USB mic")]
    assert world.events == ["peek", "peek"]

    clock.t = 9.0  # well inside the rescan window, but the streams are on the old device
    assert monitor.poll_once() is False  # same name: no second notification
    assert monitor.last_action == CYCLE
    assert world.events[2:] == ["release morse", "reinit", "reacquire morse"]
    clock.t = 12.0
    monitor.poll_once()
    assert monitor.last_action == PEEK, "the rebind is done; back to peeking"
    assert morse.mic_open and world.reinits_with_a_stream_open == 0


def test_never_during_a_hold_to_talk_recording():
    world, clock = World(peek_device="MicA", recording=True), Clock()
    morse = FakeStream(world, "morse")
    monitor = _monitor(world, clock)
    for t in (3.0, 30.0, 60.0, 600.0, 6000.0):
        clock.t = t
        assert monitor.poll_once() is False
        assert monitor.last_action == SKIP
    assert world.events == [] and morse.mic_open


def test_a_recording_that_begins_during_the_cycle_is_never_reinitialised_under():
    world, clock = World(), Clock()
    morse = FakeStream(world, "morse")
    joystick = FakeStream(world, "joystick")
    morse.on_release = lambda: setattr(world, "recording", True)  # a hold lands right now
    monitor = _monitor(world, clock, peek=False)
    clock.t = LEVEL_STREAM_RESCAN_S
    assert monitor.poll_once() is False
    assert "reinit" not in world.events and world.reinits_while_recording == 0
    assert morse.mic_open and joystick.mic_open, "what was closed is reopened anyway"
    # The failed attempt counts: it does not retry on every poll while the hold lasts.
    world.recording = False
    clock.t = LEVEL_STREAM_RESCAN_S + 3.0
    monitor.poll_once()
    assert "reinit" not in world.events


def test_a_user_mid_gesture_defers_the_cycle_until_they_stop():
    world, clock = World(peek_device="MicA"), Clock()
    switch = FakeStream(world, "switch")
    switch.engaged = True  # a scan is running
    monitor = _monitor(world, clock)
    clock.t = LEVEL_STREAM_RESCAN_S + 1.0
    monitor.poll_once()
    assert monitor.last_action == PEEK and switch.mic_open
    switch.engaged = False  # the scan ended
    clock.t += 3.0
    monitor.poll_once()
    assert monitor.last_action == CYCLE and switch.mic_open
    assert world.reinits_with_a_stream_open == 0


def test_a_gesture_that_never_ends_is_cut_only_at_the_backstop():
    world, clock = World(peek_device="MicA"), Clock()
    morse = FakeStream(world, "morse")
    morse.engaged = True
    monitor = _monitor(world, clock)
    clock.t = 3.0
    monitor.poll_once()  # engagement first seen here
    clock.t = 3.0 + ENGAGED_DEFER_MAX_S - 1.0
    monitor.poll_once()
    assert monitor.last_action == PEEK
    clock.t = 3.0 + ENGAGED_DEFER_MAX_S
    monitor.poll_once()
    assert monitor.last_action == CYCLE and world.reinits_with_a_stream_open == 0


def test_a_pause_while_the_stream_is_closed_is_not_undone_by_the_reopen():
    world, clock = World(), Clock()
    joystick = FakeStream(world, "joystick")
    joystick.on_release = joystick.user_pause  # `handsfree pause` lands mid-cycle
    monitor = _monitor(world, clock, peek=False)
    clock.t = LEVEL_STREAM_RESCAN_S
    monitor.poll_once()
    assert "reinit" in world.events
    assert joystick.mic_open is False, "a re-scan must never re-arm what the user paused"


def test_one_owner_failing_does_not_stop_the_others_or_the_monitor():
    world, clock = World(), Clock()
    stuck = FakeStream(world, "stuck")
    stuck.release_raises = True
    morse = FakeStream(world, "morse")
    morse.reacquire_raises = True
    monitor = _monitor(world, clock, peek=False)
    clock.t = LEVEL_STREAM_RESCAN_S
    assert monitor.poll_once() is False  # contained, no raise
    # The stuck stream is still open, so PortAudio was not re-initialised under it.
    assert world.reinits_with_a_stream_open == 0 and "reinit" not in world.events


def test_without_level_streams_the_monitor_behaves_exactly_as_before():
    world, clock, fired = World(), Clock(), []
    monitor = DeviceMonitor(
        poll_fn=world.poll, is_idle=world.is_idle,
        on_change=lambda prev, cur: fired.append((prev, cur)), clock=clock,
    )
    assert monitor.poll_once() is False and monitor.last_action == RESCAN
    world.device = "MicB"
    assert monitor.poll_once() is True
    assert fired == [("MicA", "MicB")]
    world.recording = True
    assert monitor.poll_once() is False and monitor.last_action == SKIP


# --------------------------------------------------------------------------- #
# The real runners: release closes, reacquire reopens only what release closed
# --------------------------------------------------------------------------- #
class FakeRecorder:
    def __init__(self, on_chunk) -> None:
        self.on_chunk = on_chunk
        self.started = 0
        self.stopped = 0

    @property
    def open(self) -> bool:
        return self.started > self.stopped

    def start(self) -> None:
        self.started += 1

    def stop(self):
        self.stopped += 1
        return np.zeros(0, dtype=np.float32)


def _factory(made: list[FakeRecorder]):
    def make(on_chunk):
        rec = FakeRecorder(on_chunk)
        made.append(rec)
        return rec

    return make


# ---- Vocal Morse ------------------------------------------------------------------------
def _morse(clock: Clock, *, stop_flag=None, entry_hum_s: float = 1.5):
    from yazses.morsevox.runtime import build_morse_runner

    made: list[FakeRecorder] = []
    cfg = types.SimpleNamespace(enabled=True, dot_max_ms=200.0, letter_gap_ms=600.0,
                                word_gap_ms=1400.0, entry_hum_s=entry_hum_s, exit_silence_s=3.0)
    runner, notes = build_morse_runner(
        cfg, threshold=0.02, recorder_factory=_factory(made), inject=lambda text: None,
        stop_requested=stop_flag, clock=clock, thread=False,
    )
    assert runner is not None, notes
    return runner, made


def test_morse_release_closes_the_hum_listener_and_reacquire_reopens_it():
    runner, made = _morse(Clock())
    runner.start()
    assert runner.mic_open and runner.mic_engaged is False  # listening is not engaged
    assert runner.release_mic_for_rescan() is True
    assert not made[0].open and not runner.mic_open
    assert runner.reacquire_mic_after_rescan() == (True, "")
    assert len(made) == 2 and made[1].open and runner.mic_open


def test_morse_release_of_a_closed_stream_reopens_nothing():
    runner, made = _morse(Clock())
    assert runner.release_mic_for_rescan() is False
    runner.reacquire_mic_after_rescan()
    assert made == []


def test_morse_pause_during_the_rescan_wins():
    runner, made = _morse(Clock())
    runner.start()
    runner.release_mic_for_rescan()
    runner.toggle("pause", [], [])
    runner.reacquire_mic_after_rescan()
    assert len(made) == 1 and not runner.mic_open


def test_morse_gate_stop_during_the_rescan_wins():
    stop = {"on": False}
    runner, made = _morse(Clock(), stop_flag=lambda: stop["on"])
    runner.start()
    runner.release_mic_for_rescan()
    stop["on"] = True
    runner.reacquire_mic_after_rescan()
    assert len(made) == 1 and not runner.mic_open


def test_morse_mode_on_a_live_stream_is_engaged_and_a_dead_stream_is_not():
    clock = Clock(100.0)
    runner, made = _morse(clock)
    runner.start()
    assert runner.enter_by_command() == (True, "")
    made[0].on_chunk(np.zeros(320, dtype=np.float32))  # audio arriving now
    assert runner.active and runner.mic_engaged is True
    clock.t += ENGAGED_AUDIO_FRESH_S + 1.0  # the mic was unplugged: no callback since
    assert runner.active, "the mode froze, as it does on a dead stream"
    assert runner.mic_engaged is False, "a frozen mode must not hold the re-scan off"


def test_a_command_entered_morse_stream_is_not_reopened_after_a_forced_release():
    runner, made = _morse(Clock(), entry_hum_s=0)
    runner.enter_by_command()
    assert runner.mic_open
    assert runner.release_mic_for_rescan() is True  # the backstop: ends the mode
    runner.reacquire_mic_after_rescan()
    assert not runner.active and len(made) == 1, "that stream existed only for the mode"


# ---- Mouth-Sound Switch -----------------------------------------------------------------
@dataclass(frozen=True)
class Ev:
    t_s: float
    kind: str
    action: str | None


class FakeDetector:
    def __init__(self) -> None:
        self.pending: list[Ev] = []

    def feed(self, chunk):
        out, self.pending = self.pending, []
        return out

    def reset(self) -> None:
        self.pending = []


def _switch(clock: Clock, *, stop_flag=None):
    from yazses.mouthswitch.runtime import MouthSwitchRunner, MouthSwitchRuntime
    from yazses.mouthswitch.scanner import DEFAULT_SCAN_ITEMS, parse_scan_items

    made: list[FakeRecorder] = []
    items, _ = parse_scan_items(list(DEFAULT_SCAN_ITEMS))
    detector = FakeDetector()
    runner = MouthSwitchRunner(
        items, recorder_factory=_factory(made),
        run_command=lambda phrase: types.SimpleNamespace(executed=True),
        sink=FakePointerSink(), sample_rate=SR, interval_s=1.0, clock=clock,
        detector=detector, stop_requested=stop_flag, thread=False,
    )
    return MouthSwitchRuntime(runner=runner), made, detector


def test_switch_release_and_reacquire_through_the_runtime_surface():
    runtime, made, _ = _switch(Clock())
    runtime.toggle("resume", [], [])
    assert runtime.mic_open and runtime.mic_engaged is False
    assert runtime.release_mic_for_rescan() is True and not runtime.mic_open
    runtime.reacquire_mic_after_rescan()
    assert runtime.mic_open and len(made) == 2


def test_switch_pause_during_the_rescan_wins():
    runtime, made, _ = _switch(Clock())
    runtime.toggle("resume", [], [])
    runtime.release_mic_for_rescan()
    runtime.toggle("pause", [], [])
    runtime.reacquire_mic_after_rescan()
    assert not runtime.mic_open and len(made) == 1


def test_a_running_scan_is_engaged_only_while_audio_arrives():
    clock = Clock(10.0)
    runtime, made, detector = _switch(clock)
    runtime.toggle("resume", [], [])
    detector.pending = [Ev(0.01, "pop", "toggle")]
    made[0].on_chunk(np.zeros(320, dtype=np.float32))  # a pop: the scan starts
    assert runtime.status_payload()["scanning"] is True
    assert runtime.mic_engaged is True
    clock.t += ENGAGED_AUDIO_FRESH_S + 1.0  # still inside the scan's own span, no audio since
    assert runtime.status_payload()["scanning"] is True
    assert runtime.mic_engaged is False


def test_a_runtime_with_no_runner_answers_the_surface_harmlessly():
    from yazses.mouthswitch.runtime import MouthSwitchRuntime
    from yazses.vocaljoystick.runtime import VocalJoystickRuntime

    for runtime in (MouthSwitchRuntime(), VocalJoystickRuntime()):
        assert runtime.mic_open is False and runtime.mic_engaged is False
        assert runtime.release_mic_for_rescan() is False
        assert runtime.reacquire_mic_after_rescan() == (True, "")


# ---- Vocal Joystick ---------------------------------------------------------------------
def _joystick(clock: Clock, *, stop_flag=None):
    from yazses.vocaljoystick.runtime import VocalJoystickRunner, VocalJoystickRuntime

    made: list[FakeRecorder] = []
    runner = VocalJoystickRunner(FakePointerSink(), recorder_factory=_factory(made),
                                 stop_requested=stop_flag, thread=False, clock=clock)
    return VocalJoystickRuntime(runner=runner), made


def test_joystick_release_and_reacquire_through_the_runtime_surface():
    runtime, made = _joystick(Clock())
    runtime.toggle("resume", [], [])
    assert runtime.release_mic_for_rescan() is True and not runtime.mic_open
    runtime.reacquire_mic_after_rescan()
    assert runtime.mic_open and len(made) == 2


def test_joystick_gate_stop_during_the_rescan_wins():
    stop = {"on": False}
    runtime, made = _joystick(Clock(), stop_flag=lambda: stop["on"])
    runtime.toggle("resume", [], [])
    runtime.release_mic_for_rescan()
    stop["on"] = True
    runtime.reacquire_mic_after_rescan()
    assert not runtime.mic_open and len(made) == 1


def test_joystick_a_user_resume_mid_rescan_is_not_doubled():
    runtime, made = _joystick(Clock())
    runtime.toggle("resume", [], [])
    runtime.release_mic_for_rescan()
    runtime.toggle("resume", [], [])  # `handsfree resume` while the stream was closed
    runtime.reacquire_mic_after_rescan()
    assert runtime.mic_open and len(made) == 2, "one stream, opened once"


def test_a_held_vowel_is_engaged_until_the_stream_goes_quiet_or_dead():
    clock = Clock(50.0)
    runtime, made = _joystick(clock)
    runtime.toggle("resume", [], [])
    assert runtime.mic_engaged is False
    audio = vowel(PETERSON_BARNEY_MALE["i"], 0.6)
    for i in range(0, audio.size, 512):
        made[0].on_chunk(audio[i:i + 512])
    assert runtime.mic_engaged is True  # mid-"eee"
    clock.t += ENGAGED_AUDIO_FRESH_S + 1.0  # unplugged mid-vowel: the driver froze
    assert runtime.mic_engaged is False


def test_the_driver_is_engaged_only_while_a_sound_is_held():
    from yazses.vocaljoystick.control import VocalJoystick
    from yazses.vocaljoystick.drive import SustainedVowelDriver

    driver = SustainedVowelDriver(VocalJoystick())
    assert driver.engaged is False
    driver._voiced_run = 3
    assert driver.engaged is True
    driver.reset()
    assert driver.engaged is False
