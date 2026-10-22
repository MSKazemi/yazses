"""Vocal Morse runtime (ADR-v2-105) — `morsevox/runtime.py`, the impure shell, with fakes.

No microphone, no audio library, no injector: a fake recorder stands in for
`AudioRecorder`, a list stands in for the injector, and time comes from a fake clock. The
per-sample path is driven by hand (``thread=False``) except in the one test that proves the
worker thread delivers the same text.

What is pinned: when the stream is open and closed, that decoded characters reach
``inject`` and nothing else does, that dictation, a pause and the global gate end the mode,
that a failing injector stops nothing, and that ``status()`` never carries a decoded character.
"""
from __future__ import annotations

import time
import types

import numpy as np
import pytest

from tests.test_morsevox_mode import LOUD, QUIET, STEP, levels, morse_runs
from yazses.morsevox.runtime import MorseRunner, build_morse_runner


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


class Clock:
    """Seconds, as `time.monotonic` returns them."""

    def __init__(self, t_s: float = 0.0) -> None:
        self.t = t_s

    def __call__(self) -> float:
        return self.t


def _cfg(**kw):
    base = dict(enabled=True, dot_max_ms=200.0, letter_gap_ms=600.0, word_gap_ms=1400.0,
                entry_hum_s=1.5, exit_silence_s=3.0)
    base.update(kw)
    return types.SimpleNamespace(**base)


def _runner(*, threshold=0.02, thread=False, factory=None, **kw):
    made: list[FakeRecorder] = []
    typed: list[str] = []
    changes: list[tuple[bool, str]] = []
    clock = kw.pop("clock", Clock())

    def default_factory(on_chunk):
        rec = FakeRecorder(on_chunk)
        made.append(rec)
        return rec

    cfg_kw = {k: kw.pop(k) for k in ("entry_hum_s", "exit_silence_s") if k in kw}
    runner, notes = build_morse_runner(
        _cfg(**cfg_kw), threshold=threshold,
        recorder_factory=factory or default_factory,
        inject=kw.pop("inject", typed.append),
        on_change=lambda active, reason: changes.append((active, reason)),
        clock=clock, thread=thread, **kw,
    )
    assert runner is not None, notes
    return runner, made, typed, changes, clock


def feed(runner: MorseRunner, samples) -> None:
    for t, lv in samples:
        runner.process(t, lv)


# --------------------------------------------------------------------------- #
# Building
# --------------------------------------------------------------------------- #
def test_a_disabled_section_builds_nothing():
    assert build_morse_runner(_cfg(enabled=False), threshold=0.02,
                              recorder_factory=FakeRecorder, inject=print) == (None, [])


def test_no_usable_threshold_builds_nothing_and_says_why():
    runner, notes = build_morse_runner(_cfg(), threshold=0.0, recorder_factory=FakeRecorder,
                                       inject=print)
    assert runner is None and notes and "threshold" in notes[0]


def test_building_opens_no_microphone():
    runner, made, *_ = _runner()
    assert made == [] and runner.mic_open is False


def test_the_config_reaches_the_mode():
    runner, *_ = _runner(entry_hum_s=2.0, exit_silence_s=4.0)
    assert runner.config.entry_hum_ms == 2000.0 and runner.config.exit_silence_ms == 4000.0
    assert runner.config.on_level == 0.02


# --------------------------------------------------------------------------- #
# When the microphone is open
# --------------------------------------------------------------------------- #
def test_with_the_hum_entry_on_start_opens_the_stream_and_stop_closes_it():
    runner, made, *_ = _runner()
    assert runner.start() == (True, "")
    (rec,) = made
    assert rec.open and runner.mic_open
    assert runner.start() == (True, "")  # idempotent: no second stream
    assert len(made) == 1
    runner.stop()
    assert not rec.open and not runner.mic_open


def test_with_the_hum_entry_off_start_opens_nothing():
    runner, made, *_ = _runner(entry_hum_s=0)
    assert runner.start() == (True, "")
    assert made == []


def test_the_spoken_command_opens_the_stream_and_the_exit_closes_it_again():
    runner, made, typed, changes, clock = _runner(entry_hum_s=0)
    assert runner.enter_by_command() == (True, "")
    (rec,) = made
    assert rec.open and runner.active
    assert changes == [(True, "command")]
    samples, _ = levels([(200, QUIET), (100, LOUD), (4000, QUIET)])
    feed(runner, samples)
    assert "".join(typed) == "e "
    assert changes[-1] == (False, "silence")
    assert not rec.open, "a stream opened for one Morse session must close when it ends"


def test_with_the_hum_entry_on_the_stream_stays_open_after_the_mode_ends():
    runner, made, typed, changes, _ = _runner()
    runner.start()
    samples, _ = levels([(2000, LOUD)] + morse_runs("e") + [(4000, QUIET)])
    feed(runner, samples)
    assert "".join(typed) == "e "
    assert [c for c in changes] == [(True, "hum"), (False, "silence")]
    assert made[0].open, "it keeps listening for the next entry hum"


def test_a_microphone_that_will_not_open_is_reported_not_raised():
    def broken(on_chunk):
        raise OSError("no device")

    runner, *_ = _runner(factory=broken)
    ok, reason = runner.start()
    assert ok is False and "OSError" in reason
    runner2, *_ = _runner(factory=broken, entry_hum_s=0)
    ok, reason = runner2.enter_by_command()
    assert ok is False and "microphone" in reason and runner2.active is False


# --------------------------------------------------------------------------- #
# What reaches the injector
# --------------------------------------------------------------------------- #
def test_only_decoded_morse_is_typed():
    runner, _made, typed, *_ = _runner()
    runner.start()
    samples, end = levels([(500, QUIET), (2000, LOUD)] + morse_runs("sos") + [(3500, QUIET)])
    feed(runner, samples)
    assert "".join(typed) == "sos "
    assert runner.typed_chars == 4


def test_speech_shaped_levels_type_nothing_and_enter_nothing():
    from tests.test_morsevox_mode import breathless, syllabic

    runner, _made, typed, changes, _ = _runner()
    runner.start()
    first, end = levels([(10_000, syllabic)])
    second, _ = levels([(10_000, breathless)], t0=end)  # time keeps moving forward
    feed(runner, first + second)
    assert typed == [] and changes == []


def test_a_failing_injector_is_logged_once_and_stops_nothing(caplog):
    calls: list[str] = []

    def broken(text: str) -> None:
        calls.append(text)
        raise RuntimeError("no focus")

    runner, *_ = _runner(inject=broken)
    runner.start()
    samples, _ = levels([(2000, LOUD)] + morse_runs("ee") + [(500, QUIET)])
    with caplog.at_level("WARNING", logger="yazses.morsevox.runtime"):
        feed(runner, samples)
    assert calls == ["e", "e", " "]  # it kept trying, letter by letter, then the word gap
    assert runner.typed_chars == 0
    assert runner.fault == "" and runner.active
    assert sum("could not type" in r.getMessage() for r in caplog.records) == 1


def test_the_stream_callback_reduces_a_chunk_to_its_mean_absolute_level():
    seen: list[tuple[float, float]] = []
    runner, made, *_ = _runner(clock=Clock(12.5))
    runner.process = lambda t, lv: seen.append((t, lv))  # type: ignore[method-assign]
    runner.start()
    made[0].on_chunk(np.array([0.02, -0.04, 0.0, 0.06], dtype=np.float32))
    made[0].on_chunk(np.zeros(0, dtype=np.float32))
    assert seen[0] == (12500.0, pytest.approx(0.03))
    assert seen[1] == (12500.0, 0.0)


# --------------------------------------------------------------------------- #
# What ends the mode
# --------------------------------------------------------------------------- #
def test_dictation_starting_ends_the_mode():
    busy = [False]
    runner, _made, typed, changes, _ = _runner(busy=lambda: busy[0])
    runner.start()
    assert runner.enter_by_command() == (True, "")
    runner.process(0.0, QUIET)
    busy[0] = True
    runner.process(STEP, LOUD)
    assert changes == [(True, "command"), (False, "dictation")]
    assert typed == []


def test_a_hum_while_dictation_records_does_not_enter():
    runner, _made, _typed, changes, _ = _runner(busy=lambda: True)
    runner.start()
    feed(runner, levels([(5000, LOUD)])[0])
    assert changes == []


def test_a_busy_check_that_raises_is_read_as_busy():
    def explode() -> bool:
        raise RuntimeError

    runner, _made, _typed, changes, _ = _runner(busy=explode)
    runner.start()
    feed(runner, levels([(5000, LOUD)])[0])
    assert changes == [] and runner.fault == ""


def test_a_pause_from_the_global_gate_ends_the_mode_and_blocks_the_hum():
    paused = [False]
    runner, _made, _typed, changes, _ = _runner(stop_requested=lambda: paused[0])
    runner.start()
    assert runner.enter_by_command() == (True, "")
    paused[0] = True
    runner.process(0.0, QUIET)
    assert changes == [(True, "command"), (False, "paused")]
    feed(runner, levels([(5000, LOUD)], t0=20.0)[0])
    assert changes[-1] == (False, "paused")  # no entry while paused
    assert runner.enter_by_command()[0] is False


def test_handsfree_pause_and_resume_through_toggle():
    runner, made, *_ = _runner()
    runner.start()
    scope: list[str] = []
    reasons: list[str] = []
    assert runner.toggle("pause", scope, reasons) is True
    assert scope == ["Vocal Morse"] and not made[0].open
    ok, reason = runner.enter_by_command()
    assert ok is False and "handsfree resume" in reason
    # A second pause of a closed stream claims nothing.
    scope2: list[str] = []
    runner.toggle("pause", scope2, reasons)
    assert scope2 == []
    scope3: list[str] = []
    assert runner.toggle("resume", scope3, reasons) is True
    assert scope3 == ["Vocal Morse (listening for the entry hum)"]
    assert made[-1].open and len(made) == 2
    assert reasons == []


def test_resume_without_the_hum_entry_reopens_nothing_and_claims_nothing():
    runner, made, *_ = _runner(entry_hum_s=0)
    scope: list[str] = []
    reasons: list[str] = []
    assert runner.toggle("resume", scope, reasons) is True
    assert (scope, reasons, made) == ([], [], [])


def test_a_resume_that_cannot_open_the_microphone_says_so():
    def broken(on_chunk):
        raise OSError

    runner, *_ = _runner(factory=broken)
    scope: list[str] = []
    reasons: list[str] = []
    assert runner.toggle("resume", scope, reasons) is False
    assert scope == [] and reasons and reasons[0].startswith("Vocal Morse:")


def test_stop_ends_an_active_mode_and_says_so():
    runner, made, _typed, changes, _ = _runner()
    runner.start()
    runner.enter_by_command()
    runner.stop()
    assert changes == [(True, "command"), (False, "stopped")]
    assert not made[0].open
    runner.stop()  # idempotent
    assert changes[-1] == (False, "stopped") and len(changes) == 2


# --------------------------------------------------------------------------- #
# Status: flags and a count, never a character
# --------------------------------------------------------------------------- #
def test_status_never_carries_what_was_typed():
    runner, _made, typed, *_ = _runner()
    runner.start()
    feed(runner, levels([(2000, LOUD)] + morse_runs("sos") + [(1000, QUIET)])[0])
    assert "".join(typed).startswith("sos")
    status = runner.status()
    assert set(status) == {"active", "state", "entered_by", "listening", "hum_entry",
                           "paused", "fault", "typed_chars"}
    for value in status.values():
        if isinstance(value, str):  # only fixed names (and an empty fault) are strings here
            assert value in {"idle", "armed", "morse", "hum", "command", ""}, value
    assert "sos" not in repr(status)
    assert status["active"] is True and status["entered_by"] == "hum"
    # The trailing quiet is a word gap, so the decoder types "sos " -- the count is
    # every character typed, not the letters alone.
    assert status["typed_chars"] == len("".join(typed))


# --------------------------------------------------------------------------- #
# The worker thread delivers the same result
# --------------------------------------------------------------------------- #
def test_the_threaded_path_types_the_same_text():
    """Chunks pushed through the real stream callback and worker. Time is a fake clock that
    advances one 20 ms chunk per callback, so the run does not depend on scheduling."""

    class StepClock:
        def __init__(self) -> None:
            self.t = 0.0

        def __call__(self) -> float:
            return self.t

    clock = StepClock()
    runner, made, typed, _changes, _ = _runner(thread=True, clock=clock)
    try:
        assert runner.start() == (True, "")
        samples, _ = levels([(2000, LOUD)] + morse_runs("e") + [(2500, QUIET)])
        for t, lv in samples:
            clock.t = t / 1000.0
            made[0].on_chunk(np.full(320, lv, dtype=np.float32))
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and "".join(typed) != "e ":
            time.sleep(0.01)
        assert "".join(typed) == "e "
    finally:
        runner.stop()
