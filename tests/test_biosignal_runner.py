"""Properties of ``yazses.biosignal.runner`` (spec: design/specs/biosignal-pipeline.md).

The runner is driven with a fake block source, a fake detector inside a real
``BiosignalPipeline`` and an injected clock. ``step()`` -- the documented unit-test seam --
gives single-threaded determinism; the few tests that need a thread use ``threading.Event``
with bounded waits and always stop the runner in a ``finally``.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from enum import Enum
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from yazses.biosignal import runner as rn
from yazses.biosignal.fprate import ActivationLedger, GovernorAction
from yazses.biosignal.pipeline import BiosignalPipeline, PipelineParts
from yazses.biosignal.runner import (
    DEFAULT_MODE_MAP,
    BiosignalRunner,
    RunnerCallbacks,
    build_runner_from_config,
)
from yazses.biosignal.types import BioEvent, ChannelInfo, EventKind, SampleBlock, SignalKind

FS = 100.0
CH = (ChannelInfo("emg0", SignalKind.EMG),)
ON, OFF = EventKind.SQUEEZE_ON, EventKind.SQUEEZE_OFF
WAIT = 5.0

posix_only = pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")


def blk(i: int = 0) -> SampleBlock:
    return SampleBlock(data=np.zeros((1, 100)), fs=FS, channels=CH, t0=float(i))


def ev(kind, conf=1.0, **detail) -> BioEvent:
    return BioEvent(kind=kind, t=0.5, confidence=conf, channel="emg0", detail=dict(detail))


# ---------------------------------------------------------------------------
# Fakes


class FakeSource:
    """Items are SampleBlocks, ``None``, exceptions (raised) or callables (called)."""

    fs = FS
    channels = CH

    def __init__(self, items=(), *, eof=True, start_error=None):
        self.items = list(items)
        self.eof = eof
        self.start_error = start_error
        self.started = False
        self.stops = 0

    def start(self):
        if self.start_error is not None:
            raise self.start_error
        self.started = True

    def read(self):
        if not self.items:
            if self.eof:
                raise EOFError
            return None
        item = self.items.pop(0)
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            return item()
        return item

    def stop(self):
        self.stops += 1


class QueueDetector:
    """Returns whatever was pushed for the next block; logs resets into ``log``."""

    def __init__(self, log):
        self.queue: list[list[BioEvent]] = []
        self.log = log

    def push(self, events):
        self.queue.append(list(events))

    def process(self, block):
        return self.queue.pop(0) if self.queue else []

    def reset(self):
        self.log.append("reset")


class Level(Enum):
    HARD = "hard"


class Rig:
    """A runner wired to fakes, plus the callback record."""

    def __init__(self, *, ledger=False, governor=None, watchdog=1.5, ledger_path=None,
                 autosave=60.0, mode_map=None, intent_map=None, source=None):
        self.t = [100.0]
        self.log: list[str] = []
        self.starts: list[str] = []
        self.ends = 0
        self.end_threads: list[int] = []
        self.intents: list = []
        self.fail_end = 0           # how many on_mode_end calls should raise
        self.fail_start = False
        self.fail_intent = False
        self.started = threading.Event()
        self.ended = threading.Event()
        self.detector = QueueDetector(self.log)
        self.ledger = ActivationLedger(clock=lambda: self.t[0]) if ledger else None
        self.governor = governor
        self.source = source or FakeSource(eof=False)
        self.n = 0
        cbs = RunnerCallbacks(on_mode_start=self._start, on_mode_end=self._end,
                              on_intent=self._intent)
        self.runner = BiosignalRunner(
            lambda: self.source, self._pipeline, cbs, mode_map=mode_map, intent_map=intent_map,
            watchdog_seconds=watchdog, poll_seconds=0.001, clock=lambda: self.t[0],
            ledger_path=ledger_path, autosave_seconds=autosave)

    # callbacks ------------------------------------------------------------
    def _start(self, mode):
        self.log.append(f"start:{mode}")
        self.starts.append(mode)
        self.started.set()
        if self.fail_start:
            raise RuntimeError("start exploded")

    def _end(self):
        self.log.append("end")
        self.ends += 1
        self.end_threads.append(threading.get_ident())
        self.ended.set()
        if self.fail_end > 0:
            self.fail_end -= 1
            raise RuntimeError("end exploded")

    def _intent(self, intent):
        self.intents.append(intent)
        if self.fail_intent:
            raise RuntimeError("intent exploded")

    def _pipeline(self, source):
        return BiosignalPipeline(PipelineParts(
            detectors=[self.detector], ledger=self.ledger, governor=self.governor))

    # driving --------------------------------------------------------------
    def attach(self):
        """Install source and pipeline without running (the ``step()`` seam)."""
        self.runner._source = self.source
        self.runner._pipeline = self._pipeline(self.source)
        return self

    def advance(self, dt):
        self.t[0] += dt

    def step(self, events=()):
        self.detector.push(events)
        self.source.items.append(blk(self.n))
        self.n += 1
        assert self.runner.step() is True

    def run_in_thread(self):
        thread = threading.Thread(target=self.runner.run, daemon=True)
        thread.start()
        return thread


def wait_for(predicate, timeout=WAIT):
    """Poll a condition with a short sleep, bounded; returns the final truth value."""
    stop = threading.Event()
    for _ in range(int(timeout / 0.005)):
        if predicate():
            return True
        stop.wait(0.005)
    return predicate()


# ---------------------------------------------------------------------------
# Callback contract


def test_light_squeeze_starts_full_text_hard_squeeze_starts_command():
    rig = Rig().attach()
    rig.step([ev(ON, level="light")])
    assert rig.starts == ["full_text"]
    rig.step([ev(OFF)])
    rig.step([ev(ON, level="hard")])
    assert rig.starts == ["full_text", "command"]


def test_squeeze_without_a_level_uses_the_on_fallback():
    rig = Rig().attach()
    rig.step([ev(ON)])
    assert rig.starts == [DEFAULT_MODE_MAP["on"]]


def test_level_may_be_an_enum_and_may_come_from_the_mode_key():
    rig = Rig().attach()
    rig.step([ev(ON, level=Level.HARD)])
    rig.step([ev(OFF)])
    rig.step([ev(ON, mode="light")])
    assert rig.starts == ["command", "full_text"]


def test_level_change_while_held_calls_start_again_but_same_level_does_not():
    rig = Rig().attach()
    rig.step([ev(ON, level="light")])
    rig.step([ev(ON, level="light")])
    assert rig.starts == ["full_text"]
    rig.step([ev(ON, level="hard")])
    assert rig.starts == ["full_text", "command"]
    assert rig.ends == 0                                # a level change is not a release
    assert rig.runner.status()["mode"] == "command"


def test_custom_mode_map_is_honoured_and_unmapped_levels_are_ignored():
    rig = Rig(mode_map={"Light": "dictate", "hard": ""}).attach()   # empty value drops the key
    rig.step([ev(ON, level="light")])
    rig.step([ev(OFF)])
    rig.step([ev(ON, level="hard")])                    # no mode for hard, no "on" fallback
    assert rig.starts == ["dictate"]
    assert rig.runner.status()["squeeze_active"] is False


def test_on_mode_end_is_called_only_if_a_mode_was_held():
    rig = Rig().attach()
    rig.step([ev(OFF)])                                  # orphan OFF
    assert rig.ends == 0
    rig.step([ev(ON)])
    rig.step([ev(OFF)])
    assert rig.ends == 1
    rig.step([ev(OFF)])
    assert rig.ends == 1
    rig.runner.stop()
    assert rig.ends == 1                                 # nothing was held at stop


def test_start_end_pairs_for_repeated_squeezes():
    rig = Rig().attach()
    for _ in range(3):
        rig.step([ev(ON)])
        rig.step([ev(OFF)])
    assert rig.log == ["start:full_text", "end"] * 3


def test_squeeze_that_starts_and_ends_in_one_block_still_pairs():
    rig = Rig().attach()
    rig.step([ev(ON), ev(OFF)])
    assert rig.log == ["start:full_text", "end"]


# ---------------------------------------------------------------------------
# Intents


def test_double_blink_becomes_an_undo_intent_and_is_counted():
    rig = Rig().attach()
    rig.step([ev(EventKind.DOUBLE_BLINK, 0.8)])
    assert [(i.label, i.confidence) for i in rig.intents] == [("undo", 0.8)]
    assert rig.runner.status()["intents"] == 1
    assert rig.runner.vocabulary == ("undo",)


def test_unmapped_events_produce_no_intent_and_squeezes_never_do():
    rig = Rig().attach()
    rig.step([ev(EventKind.JAW_CLENCH), ev(EventKind.BLINK), ev(ON), ev(OFF)])
    assert rig.intents == []


def test_custom_intent_map_maps_jaw_clench():
    rig = Rig(intent_map={"jaw_clench": "send"}).attach()
    rig.step([ev(EventKind.JAW_CLENCH), ev(EventKind.DOUBLE_BLINK)])
    assert [i.label for i in rig.intents] == ["send"]
    assert rig.runner.vocabulary == ("send",)


def test_raising_intent_callback_is_caught():
    rig = Rig().attach()
    rig.fail_intent = True
    rig.step([ev(EventKind.DOUBLE_BLINK)])
    rig.step([ev(EventKind.DOUBLE_BLINK)])
    assert len(rig.intents) == 2


# ---------------------------------------------------------------------------
# Stuck-key invariants


def test_check_watchdog_releases_a_held_squeeze_once_after_the_period():
    rig = Rig(watchdog=1.5).attach()
    rig.step([ev(ON)])
    rig.advance(1.0)
    assert rig.runner.check_watchdog() is False          # still within the period
    assert rig.ends == 0
    rig.advance(1.0)
    assert rig.runner.check_watchdog() is True
    assert rig.runner.check_watchdog() is False          # once
    assert rig.ends == 1
    status = rig.runner.status()
    assert status["squeeze_active"] is False and status["watchdog_trips"] == 1


def test_check_watchdog_accepts_an_explicit_time_and_ignores_a_relaxed_state():
    rig = Rig(watchdog=1.5).attach()
    assert rig.runner.check_watchdog(now=10_000.0) is False   # nothing held
    rig.step([ev(ON)])
    assert rig.runner.check_watchdog(now=rig.t[0] + 1.0) is False
    assert rig.runner.check_watchdog(now=rig.t[0] + 2.0) is True


def test_watchdog_disabled_when_period_is_zero():
    rig = Rig(watchdog=0).attach()
    rig.step([ev(ON)])
    rig.advance(10_000)
    assert rig.runner.check_watchdog() is False and rig.ends == 0


def test_watchdog_thread_releases_when_no_block_arrives():
    """The real watchdog thread ends a hold once blocks stop, exactly once."""
    rig = Rig(watchdog=0.05, source=FakeSource([blk(0)], eof=False))
    rig.detector.push([ev(ON)])
    thread = rig.run_in_thread()
    try:
        assert rig.started.wait(WAIT)
        rig.advance(10.0)                                # the device goes quiet
        assert rig.ended.wait(WAIT)
        wait_for(lambda: False, 0.1)                     # give extra ticks a chance to double fire
        assert rig.ends == 1
        assert rig.runner.status()["watchdog_trips"] == 1
    finally:
        rig.runner.stop()
        thread.join(WAIT)
    assert not thread.is_alive()
    assert rig.ends == 1


def test_source_raising_mid_hold_releases_the_squeeze_and_run_returns():
    rig = Rig(watchdog=0, source=FakeSource([blk(0), RuntimeError("cable pulled")]))
    rig.detector.push([ev(ON)])
    rig.runner.run()                                     # does not raise
    assert rig.log == ["start:full_text", "end"]
    status = rig.runner.status()
    assert status["squeeze_active"] is False and status["running"] is False
    assert "cable pulled" in status["last_error"]
    assert rig.source.stops == 1


def test_finite_source_end_releases_a_held_squeeze():
    rig = Rig(watchdog=0, source=FakeSource([blk(0)]))   # then EOFError
    rig.detector.push([ev(ON)])
    rig.runner.run()
    assert rig.log == ["start:full_text", "end"]
    assert rig.runner.status()["last_error"] == ""       # EOF is not an error


def test_stop_releases_on_the_callers_thread_even_if_read_is_hung():
    """``stop()`` releases the key itself: the run thread may be stuck inside ``read``."""
    hang = threading.Event()
    reading = threading.Event()

    def hung_read():
        reading.set()
        hang.wait(WAIT * 2)
        return None

    rig = Rig(watchdog=0, source=FakeSource([blk(0), hung_read], eof=False))
    rig.detector.push([ev(ON)])
    thread = rig.run_in_thread()
    try:
        assert rig.started.wait(WAIT) and reading.wait(WAIT)
        rig.runner.stop()
        assert rig.ends == 1                              # already done, synchronously
        assert rig.end_threads == [threading.get_ident()]
        assert rig.runner.status()["squeeze_active"] is False
    finally:
        hang.set()
        rig.runner.stop()
        thread.join(WAIT)
    assert not thread.is_alive()
    assert rig.ends == 1


def test_stop_is_idempotent_and_releases_exactly_once():
    rig = Rig().attach()
    rig.step([ev(ON)])
    rig.runner.stop()
    rig.runner.stop()
    assert rig.ends == 1


def test_a_start_is_refused_once_stopping():
    """A late ON after stop() must not reopen the dictation key stop() just released."""
    rig = Rig().attach()
    rig.step([ev(ON)])
    rig.runner.stop()
    rig.step([ev(ON, level="hard")])
    assert rig.starts == ["full_text"] and rig.ends == 1
    assert rig.runner.status()["squeeze_active"] is False


def test_on_mode_end_is_retried_once_when_it_raises():
    rig = Rig().attach()
    rig.step([ev(ON)])
    rig.fail_end = 1
    rig.step([ev(OFF)])
    assert rig.ends == 2                                  # one failure, one successful retry
    assert rig.runner.status()["squeeze_active"] is False


def test_on_mode_end_that_always_raises_is_attempted_twice_and_never_propagates():
    rig = Rig().attach()
    rig.step([ev(ON)])
    rig.fail_end = 99
    rig.step([ev(OFF)])
    assert rig.ends == 2
    rig.runner.stop()
    assert rig.ends == 2                                  # state was cleared; no endless retry


def test_raising_on_mode_start_is_caught_and_the_hold_is_still_releasable():
    rig = Rig().attach()
    rig.fail_start = True
    rig.step([ev(ON)])                                    # does not raise
    rig.step([ev(OFF)])
    assert rig.log == ["start:full_text", "end"]


def test_gap_releases_the_squeeze_before_the_pipeline_is_reset():
    """After a stream gap the held squeeze is released *first*, then detectors are reset."""
    rig = Rig(watchdog=1.5).attach()
    rig.step([ev(ON)])
    rig.advance(5.0)                                      # the stream stalled and resumed
    rig.step([])
    assert rig.log == ["start:full_text", "end", "reset"]
    assert rig.runner.status()["squeeze_active"] is False


def test_no_gap_handling_within_the_watchdog_period():
    rig = Rig(watchdog=1.5).attach()
    rig.step([ev(ON)])
    rig.advance(1.0)
    rig.step([])
    assert rig.log == ["start:full_text"]


def test_pipeline_synthetic_off_reaches_the_daemon_callback():
    """A suspension decided inside the pipeline releases the key through ``on_mode_end``."""
    class Gov:
        state = "ok"

        def __init__(self):
            self.action = GovernorAction.ok()

        def update(self):
            return self.action

        def release(self):
            return GovernorAction.ok()

    gov = Gov()
    rig = Rig(governor=gov).attach()
    rig.step([ev(ON)])
    gov.action = GovernorAction.suspend("too many false activations")
    rig.step([])
    assert rig.log == ["start:full_text", "end"]


def test_stop_before_run_makes_run_return_promptly_and_close_the_source():
    rig = Rig()
    rig.runner.stop()
    rig.runner.run()
    assert rig.source.stops == 1 and rig.starts == []


# ---------------------------------------------------------------------------
# Failing to open the source is a logged no-op


def test_source_that_fails_to_open_is_a_logged_noop():
    src = FakeSource(start_error=RuntimeError("no device"))
    rig = Rig(source=src)
    rig.runner.run()                                      # no exception
    status = rig.runner.status()
    assert status["running"] is False and "no device" in status["last_error"]
    assert rig.runner.pipeline is None and rig.starts == [] and rig.ends == 0
    assert src.stops == 1                                 # a half-started device is released


def test_missing_optional_dependency_is_reported_not_raised():
    src = FakeSource(start_error=ModuleNotFoundError("No module named 'brainflow'",
                                                     name="brainflow"))
    rig = Rig(source=src)
    rig.runner.run()
    assert rig.runner.status()["last_error"] == "missing dependency: brainflow"
    assert rig.runner.pipeline is None


def test_source_factory_that_raises_is_a_noop():
    def factory():
        raise OSError("port busy")

    runner = BiosignalRunner(factory, lambda s: BiosignalPipeline())
    runner.run()
    assert "port busy" in runner.status()["last_error"]
    assert runner.status()["running"] is False


def test_failing_source_stop_during_teardown_is_tolerated():
    class BadStop(FakeSource):
        def stop(self):
            raise RuntimeError("stop exploded")

    rig = Rig(watchdog=0, source=BadStop([blk(0)]))
    rig.runner.run()
    assert rig.runner.status()["running"] is False


# ---------------------------------------------------------------------------
# Ledger persistence


def counts(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_save_writes_aggregate_counters_atomically_with_private_mode(tmp_path):
    path = tmp_path / "sub" / "ledger.json"
    rig = Rig(ledger=True, ledger_path=path).attach()
    rig.step([ev(EventKind.BLINK), ev(EventKind.JAW_CLENCH)])
    assert rig.runner.save_ledger() is True
    data = counts(path)
    assert data["activations"] == {"blink": 1, "jaw_clench": 1}
    assert set(data) == {"schema", "sessions", "active_seconds", "activations", "cancelled"}
    assert sorted(p.name for p in path.parent.iterdir()) == ["ledger.json"]   # no temp left


@posix_only
def test_ledger_file_is_owner_only(tmp_path):
    path = tmp_path / "ledger.json"
    rig = Rig(ledger=True, ledger_path=path).attach()
    rig.step([ev(EventKind.BLINK)])
    rig.runner.save_ledger()
    assert (path.stat().st_mode & 0o777) == 0o600


def test_repeated_saves_do_not_double_count(tmp_path):
    path = tmp_path / "ledger.json"
    rig = Rig(ledger=True, ledger_path=path).attach()
    rig.step([ev(EventKind.BLINK), ev(EventKind.BLINK)])
    assert rig.runner.save_ledger() is True
    assert rig.runner.save_ledger() is False              # nothing changed: no write
    rig.step([ev(EventKind.BLINK)])
    assert rig.runner.save_ledger() is True
    assert counts(path)["activations"] == {"blink": 3}    # not 2 + 3
    rig.runner.stop()                                     # final save adds nothing new
    assert counts(path)["activations"] == {"blink": 3}


def test_save_adds_only_deltas_to_a_preexisting_file(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps({"schema": 1, "sessions": 2, "active_seconds": 10,
                                "activations": {"blink": 5}, "cancelled": {"blink": 1}}), encoding="utf-8")
    rig = Rig(ledger=True, ledger_path=path).attach()
    rig.step([ev(EventKind.BLINK)] * 3)
    rig.runner.save_ledger()
    rig.step([ev(EventKind.BLINK)])
    rig.runner.save_ledger()
    data = counts(path)
    assert data["activations"] == {"blink": 9}
    assert data["cancelled"] == {"blink": 1}
    assert data["sessions"] == 3                          # 2 stored + this session, once


def test_save_keeps_totals_another_process_wrote_in_the_meantime(tmp_path):
    path = tmp_path / "ledger.json"
    rig = Rig(ledger=True, ledger_path=path).attach()
    rig.step([ev(EventKind.BLINK)])
    rig.runner.save_ledger()
    data = counts(path)
    data["activations"]["blink"] += 100                   # e.g. `yazses biosignal measure`
    path.write_text(json.dumps(data), encoding="utf-8")
    rig.step([ev(EventKind.BLINK)])
    rig.runner.save_ledger()
    assert counts(path)["activations"] == {"blink": 102}


def test_cancellations_are_recorded_and_never_exceed_activations(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps({"activations": {"blink": 1}, "cancelled": {"blink": 9}}), encoding="utf-8")
    rig = Rig(ledger=True, ledger_path=path).attach()
    rig.step([ev(EventKind.BLINK)])
    rig.runner.save_ledger()
    data = counts(path)
    assert data["activations"] == {"blink": 2}
    assert data["cancelled"] == {"blink": 2}              # clamped to the activations

    path2 = tmp_path / "second.json"
    rig2 = Rig(ledger=True, ledger_path=path2).attach()
    rig2.step([ev(EventKind.JAW_CLENCH)])
    assert rig2.runner.note_cancelled("jaw_clench") is True
    rig2.runner.save_ledger()
    assert counts(path2)["cancelled"] == {"jaw_clench": 1}


@pytest.mark.parametrize("content", [
    "{not json", "[1, 2, 3]", "null", "\x00\x01 garbage", "",
    json.dumps({"activations": {"blink": "many", "jaw_clench": True, "x": -4},
                "sessions": "two", "cancelled": 7}),
])
def test_corrupt_or_hostile_ledger_file_is_tolerated(tmp_path, content):
    path = tmp_path / "ledger.json"
    path.write_text(content, encoding="utf-8")
    rig = Rig(ledger=True, ledger_path=path).attach()
    rig.step([ev(EventKind.BLINK)])
    assert rig.runner.save_ledger() is True
    assert counts(path)["activations"] == {"blink": 1}    # junk counted as zero, file healed


def test_oversized_ledger_file_is_ignored(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps({"activations": {"blink": 5}}) + " " * (1 << 21), encoding="utf-8")
    rig = Rig(ledger=True, ledger_path=path).attach()
    rig.step([ev(EventKind.BLINK)])
    rig.runner.save_ledger()
    assert counts(path)["activations"] == {"blink": 1}


def test_memory_only_when_ledger_path_is_empty_or_none(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for value in ("", None):
        rig = Rig(ledger=True, ledger_path=value).attach()
        rig.step([ev(EventKind.BLINK)])
        assert rig.runner.persists_ledger is False
        assert rig.runner.save_ledger() is False
        rig.runner.stop()
        assert rig.runner.status()["ledger_persisted"] is False
    assert list(tmp_path.iterdir()) == []


def test_persists_ledger_is_true_with_a_path(tmp_path):
    rig = Rig(ledger_path=tmp_path / "l.json")
    assert rig.runner.persists_ledger is True
    assert rig.runner.status()["ledger_persisted"] is True


def test_save_without_a_ledger_or_without_data_writes_nothing(tmp_path):
    path = tmp_path / "ledger.json"
    assert Rig(ledger=False, ledger_path=path).attach().runner.save_ledger() is False
    rig = Rig(ledger=True, ledger_path=path).attach()
    rig.step([])                                          # a session tick alone is not data
    assert rig.runner.save_ledger() is False
    assert not path.exists()


def test_stop_saves_the_ledger_on_the_callers_thread(tmp_path):
    path = tmp_path / "ledger.json"
    rig = Rig(ledger=True, ledger_path=path).attach()
    rig.step([ev(EventKind.BLINK)])
    assert not path.exists()
    rig.runner.stop()
    assert counts(path)["activations"] == {"blink": 1}


def test_run_saves_on_exit_and_pauses_the_ledger(tmp_path):
    path = tmp_path / "ledger.json"
    rig = Rig(ledger=True, ledger_path=path, watchdog=0, source=FakeSource([blk(0)]))
    rig.detector.push([ev(EventKind.BLINK)])
    rig.runner.run()
    assert counts(path)["activations"] == {"blink": 1}
    assert rig.ledger.is_active is False                  # exposure stops with the run


def test_autosave_writes_during_the_run_at_the_configured_interval(tmp_path):
    path = tmp_path / "ledger.json"
    seen = {}

    def advance_clock():
        rig.advance(61.0)

    def check():
        seen["after_interval"] = path.exists()
        return None

    rig = Rig(ledger=True, ledger_path=path, watchdog=0, autosave=60.0,
              source=FakeSource([blk(0), lambda: seen.update(before=path.exists()),
                                 advance_clock, check]))
    rig.detector.push([ev(EventKind.BLINK)])
    rig.runner.run()
    assert seen["before"] is False and seen["after_interval"] is True


def test_autosave_can_be_disabled_but_stop_still_saves(tmp_path):
    path = tmp_path / "ledger.json"
    seen = {}
    rig = Rig(ledger=True, ledger_path=path, watchdog=0, autosave=0,
              source=FakeSource([blk(0), lambda: rig.advance(10_000.0),
                                 lambda: seen.update(exists=path.exists())]))
    rig.detector.push([ev(EventKind.BLINK)])
    rig.runner.run()
    assert seen["exists"] is False
    assert counts(path)["activations"] == {"blink": 1}


def test_failed_save_never_raises_and_a_failed_replace_keeps_the_old_file(tmp_path, monkeypatch):
    path = tmp_path / "ledger.json"
    original = {"activations": {"blink": 4}}
    path.write_text(json.dumps(original), encoding="utf-8")
    rig = Rig(ledger=True, ledger_path=path).attach()
    rig.step([ev(EventKind.BLINK)])

    def broken_replace(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(rn.os, "replace", broken_replace)
    assert rig.runner.save_ledger() is False
    monkeypatch.undo()
    assert json.loads(path.read_text(encoding="utf-8")) == original
    assert [p.name for p in tmp_path.iterdir()] == ["ledger.json"]   # temp file cleaned up
    assert rig.runner.save_ledger() is True               # the delta was kept for the next try
    assert counts(path)["activations"] == {"blink": 5}


def test_save_to_an_impossible_location_returns_false(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    rig = Rig(ledger=True, ledger_path=blocker / "ledger.json").attach()
    rig.step([ev(EventKind.BLINK)])
    assert rig.runner.save_ledger() is False
    assert rig.runner.save_ledger() is False


# ---------------------------------------------------------------------------
# build_runner_from_config


def cfg(**fields):
    return SimpleNamespace(biosignal=SimpleNamespace(**fields))


class RecordingOpen:
    def __init__(self):
        self.specs = []

    def __call__(self, spec, **kw):
        self.specs.append(spec)
        return FakeSource([blk(0)])


@pytest.fixture
def opened(monkeypatch):
    rec = RecordingOpen()
    monkeypatch.setattr("yazses.biosignal.sources.open_source", rec)
    return rec


def test_disabled_or_missing_section_gives_no_runner(opened):
    assert build_runner_from_config(SimpleNamespace()) is None
    assert build_runner_from_config(cfg(enabled=False, source="synthetic")) is None
    assert build_runner_from_config(cfg(source="synthetic")) is None     # enabled defaults off
    assert build_runner_from_config(cfg(enabled=None, source="synthetic")) is None
    assert opened.specs == []


def test_enabled_without_a_source_gives_no_runner(opened):
    for source in ("", "   ", None):
        assert build_runner_from_config(cfg(enabled=True, source=source)) is None


def test_unavailable_sources_module_gives_no_runner(monkeypatch):
    monkeypatch.setitem(sys.modules, "yazses.biosignal.sources", None)
    assert build_runner_from_config(cfg(enabled=True, source="synthetic")) is None


def test_runner_is_built_from_a_minimal_config_without_opening_anything(opened, tmp_path):
    """Only ``enabled`` and ``source`` are needed; every other field has a default."""
    runner = build_runner_from_config(cfg(enabled=True, source="synthetic:emg"),
                                      ledger_path=tmp_path / "l.json")
    assert isinstance(runner, BiosignalRunner)
    assert opened.specs == []                             # nothing opened at build time
    assert runner.persists_ledger is True


def test_ledger_path_resolution(opened, tmp_path):
    base = cfg(enabled=True, source="synthetic")
    assert build_runner_from_config(base, ledger_path="").persists_ledger is False
    assert build_runner_from_config(base, ledger_path=tmp_path / "x.json")._ledger_path == (
        tmp_path / "x.json")
    assert build_runner_from_config(base, data_dir=tmp_path)._ledger_path == (
        tmp_path / "biosignal_ledger.json")


def test_default_ledger_path_comes_from_the_platform_data_dir(opened, tmp_path, monkeypatch):
    monkeypatch.setattr(rn, "_default_ledger_path", lambda: tmp_path / "biosignal_ledger.json")
    runner = build_runner_from_config(cfg(enabled=True, source="synthetic"))
    assert runner._ledger_path == tmp_path / "biosignal_ledger.json"


def test_intent_vocabulary_follows_the_enabled_switches(opened, tmp_path):
    kw = {"ledger_path": ""}
    off = build_runner_from_config(cfg(enabled=True, source="s"), **kw)
    assert off.vocabulary == ()                           # no switch on, nothing to say
    blink = build_runner_from_config(cfg(enabled=True, source="s", double_blink=True), **kw)
    assert blink.vocabulary == ("undo",)
    jaw_off = build_runner_from_config(
        cfg(enabled=True, source="s", intent_map={"jaw_clench": "send"}), **kw)
    assert jaw_off.vocabulary == ()                       # jaw switch not enabled
    jaw_on = build_runner_from_config(
        cfg(enabled=True, source="s", jaw_clench=True, intent_map={"jaw_clench": "send"}), **kw)
    assert jaw_on.vocabulary == ("send",)


def test_mode_map_comes_from_the_config(opened):
    custom = build_runner_from_config(
        cfg(enabled=True, source="s", mode_map={"Light": "dictate", "hard": "cmd"}),
        ledger_path="")
    assert custom._mode_map == {"light": "dictate", "hard": "cmd"}
    default = build_runner_from_config(cfg(enabled=True, source="s", mode_map={}),
                                       ledger_path="")
    assert default._mode_map == DEFAULT_MODE_MAP


def test_none_valued_fields_fall_back_to_defaults(opened):
    runner = build_runner_from_config(
        cfg(enabled=True, source="s", mains_hz=None, double_blink=None, jaw_clench=None,
            emg=None, max_cancelled_per_hour=None, calibration_file=None, mode_map=None,
            intent_map=None), ledger_path="")
    assert isinstance(runner, BiosignalRunner)


def test_built_runner_runs_end_to_end_on_a_fake_source(opened, tmp_path):
    """The configured runner opens the spec inside run(), builds real parts and finishes."""
    path = tmp_path / "ledger.json"
    runner = build_runner_from_config(
        cfg(enabled=True, source="synthetic:emg", double_blink=True, max_cancelled_per_hour=6.0),
        ledger_path=path)
    runner.run()
    assert opened.specs == ["synthetic:emg"]
    status = runner.status()
    assert status["running"] is False and status["blocks"] == 1 and status["last_error"] == ""
    assert status["governor"]["state"] in {"ok", "desensitize", "suspend"}
    assert runner.pipeline is not None and runner.ledger is not None


# ---------------------------------------------------------------------------
# status() and the public API


def test_status_before_the_runner_has_run():
    status = Rig().runner.status()
    assert status["running"] is False and status["squeeze_active"] is False
    assert status["mode"] == "" and status["blocks"] == 0 and status["events"] == 0
    assert status["last_block_age_s"] is None and status["last_error"] == ""
    assert status["governor"] == {"state": "off", "explain": ""}
    assert status["ledger"] == "" and status["ledger_persisted"] is False
    assert status["vocabulary"] == ["undo"]
    assert status["pipeline"]["blocks"] == 0


def test_status_after_blocks_reports_counts_mode_and_block_age():
    rig = Rig(ledger=True).attach()
    rig.step([ev(ON, level="hard"), ev(EventKind.DOUBLE_BLINK)])
    rig.advance(0.25)
    status = rig.runner.status()
    assert status["squeeze_active"] is True and status["mode"] == "command"
    assert status["blocks"] == 1 and status["events"] == 2 and status["intents"] == 1
    assert status["last_block_age_s"] == 0.25
    assert status["pipeline"]["accepted"] == 2 and status["pipeline"]["squeeze_active"] is True
    assert isinstance(status["ledger"], str) and status["ledger"]


def test_status_reports_the_governor_state_and_tolerates_a_broken_explain():
    class Gov:
        state = "desensitize"

        def update(self):
            return GovernorAction.desensitize(1.5, "x")

        def explain(self):
            raise RuntimeError("no")

        def release(self):
            return GovernorAction.ok()

    rig = Rig(governor=Gov()).attach()
    rig.step([])
    assert rig.runner.status()["governor"] == {"state": "desensitize", "explain": ""}

    class Explaining(Gov):
        def explain(self):
            return "over budget"

    rig2 = Rig(governor=Explaining()).attach()
    rig2.step([])
    assert rig2.runner.status()["governor"]["explain"] == "over budget"


def test_public_surface_before_run():
    runner = Rig().runner
    assert runner.pipeline is None and runner.ledger is None
    assert runner.note_cancelled() is False
    assert runner.save_ledger() is False
    assert runner.governor_release().kind.value == "ok"


def test_public_surface_exposes_pipeline_and_ledger():
    rig = Rig(ledger=True).attach()
    assert isinstance(rig.runner.pipeline, BiosignalPipeline)
    assert rig.runner.ledger is rig.ledger


def test_note_cancelled_matches_by_kind_and_within_the_grace_window():
    rig = Rig(ledger=True).attach()
    rig.step([ev(EventKind.JAW_CLENCH)])
    assert rig.runner.note_cancelled(EventKind.BLINK) is False        # wrong kind
    assert rig.runner.note_cancelled("not-a-kind") is False           # unknown kind ignored
    assert rig.runner.note_cancelled("JAW_CLENCH") is True            # name or value, any case
    assert rig.runner.note_cancelled("jaw_clench") is False           # already cancelled
    rig.step([ev(EventKind.BLINK)])
    rig.advance(10.0)                                                 # past the grace window
    assert rig.runner.note_cancelled() is False
    assert rig.ledger.total_stats().cancelled == 1


def test_note_cancelled_without_a_kind_cancels_the_latest_of_any_kind():
    rig = Rig(ledger=True).attach()
    rig.step([ev(EventKind.DOUBLE_BLINK)])
    assert rig.runner.note_cancelled() is True
    assert rig.runner.note_cancelled(None) is False


def test_note_cancelled_without_a_ledger_is_false():
    rig = Rig(ledger=False).attach()
    rig.step([ev(EventKind.DOUBLE_BLINK)])
    assert rig.runner.note_cancelled() is False


def test_governor_release_is_forwarded_to_the_pipeline_and_is_idempotent():
    class Gov:
        state = "suspend"

        def __init__(self):
            self.releases = 0

        def update(self):
            return GovernorAction.suspend("budget")

        def release(self):
            self.releases += 1
            return GovernorAction.ok()

    gov = Gov()
    rig = Rig(governor=gov).attach()
    rig.step([])
    assert rig.runner.pipeline.status.suspended is True
    assert rig.runner.governor_release().kind.value == "ok"
    assert rig.runner.pipeline.status.suspended is False
    assert rig.runner.governor_release().kind.value == "ok"
    assert gov.releases == 2
