"""The `[biosignal]` switch is really wired into the daemon (ADR-v2-152).

Pins the seams in ``core/daemon.py``: nothing is built or imported while the section is off,
an enabled synthetic source becomes one activation source on the same list as ``[emg]``, the
speech callback is a SpeechGuard over the tray state, the confirmation thresholds come from
``[activation]`` only when it is on and sane, the global hands-free pause refuses and
releases a squeeze (and a Resume mid-squeeze never restarts a turn), ``handsfree resume``
also releases the false-positive governor, and a spoken undo is counted against the switch.

Nothing here opens a board, a microphone or a file outside ``tmp_path``: the runner and the
hands-free gate are fakes or run on a fabricated clock.
"""
from __future__ import annotations

import builtins
import dataclasses
import inspect
import re
import threading
import time
import types

import pytest

from yazses.activation.confirm import DEFAULT_CONFIRM_THRESHOLD, DEFAULT_REJECT_FLOOR
from yazses.activation.intent import ActivationIntent
from yazses.config import BiosignalConfig, Config
from yazses.core import daemon as daemon_module
from yazses.core.daemon import Daemon, _BiosignalGuarded
from yazses.handsfree.safety import HandsFreeSafety
from yazses.ipc.protocol import Request
from yazses.platform import get_platform
from yazses.platform.base import TrayState

SOURCE = "biosignal"


# ------------------------------------------------------------------------------ rigs


def _config(**bio) -> Config:
    cfg = Config()
    cfg.biosignal = dataclasses.replace(BiosignalConfig(), **bio)
    return cfg


def _daemon(tmp_path, **bio) -> Daemon:
    d = Daemon(config=_config(**bio), platform=get_platform())
    # Keep the activation ledger (and anything else under the data dir) inside the test.
    d._platform = types.SimpleNamespace(paths=types.SimpleNamespace(data_dir=tmp_path))
    return d


class Clock:
    """Milliseconds that only move when the test says so."""

    def __init__(self) -> None:
        self.now = 10_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, ms: float) -> None:
        self.now += ms


class FakeRunner:
    """The public surface the daemon uses: status, vocabulary, ledger and governor hooks."""

    persists_ledger = True

    def __init__(self, *, vocabulary=("undo",), age=0.1) -> None:
        self.vocabulary = tuple(vocabulary)
        self.age = age
        self.cancelled = 0
        self.released = 0

    def status(self) -> dict:
        return {"last_block_age_s": self.age}

    def note_cancelled(self, kind=None) -> bool:
        self.cancelled += 1
        return True

    def governor_release(self):
        self.released += 1

    def run(self) -> None:
        return None

    def stop(self) -> None:
        return None


class Turns:
    """Records the dictation callbacks a squeeze drives."""

    def __init__(self, d: Daemon) -> None:
        self.calls: list[str] = []
        d._on_hold_start = lambda leaked: self.calls.append("dictate")  # type: ignore[method-assign]
        d._on_command_hold_start = lambda leaked: self.calls.append("command")  # type: ignore[method-assign]
        d._on_hold_end = lambda: self.calls.append("end")  # type: ignore[method-assign]


def _rig(tmp_path, *, gate: bool = True, runner: FakeRunner | None = None, **bio):
    """A daemon with a fake runner installed, and (optionally) a real gate on a fake clock."""
    d = _daemon(tmp_path, enabled=True, source="synthetic", **bio)
    runner = runner or FakeRunner()
    d._biosignal_runner = runner
    d._biosignal = types.SimpleNamespace(vocabulary=runner.vocabulary)
    d._biosignal_lock = threading.Lock()
    clock = Clock()
    safety = HandsFreeSafety((), clock=clock) if gate else None
    d._handsfree_safety = safety
    turns = Turns(d)
    return d, runner, safety, clock, turns


def _armed(tmp_path, **kw):
    """A rig whose gate has heard from the source and been explicitly resumed."""
    d, runner, safety, clock, turns = _rig(tmp_path, **kw)
    assert d._biosignal_check_gate() is False  # first sample registers; nothing is armed yet
    assert safety.resume().ok
    assert d._biosignal_check_gate() is True
    return d, runner, safety, clock, turns


class _Spy:
    """Replaces `handle_intent`; records the thresholds an intent is judged against."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, intent, vocabulary, **kw):
        self.calls.append({"intent": intent, "vocabulary": vocabulary, **kw})
        return types.SimpleNamespace(executed=True)


@pytest.fixture
def intent_spy(monkeypatch):
    spy = _Spy()
    monkeypatch.setattr("yazses.activation.pipeline.handle_intent", spy)
    return spy


def _intent(label: str = "undo") -> ActivationIntent:
    return ActivationIntent(label=label, confidence=0.95, source="biosignal")


def _biosignal_import_spy(monkeypatch) -> list[str]:
    """Record every import REQUEST for yazses.biosignal*, cached or not."""
    requested: list[str] = []
    real_import = builtins.__import__

    def spy(name, globals=None, locals=None, fromlist=(), level=0):
        if level == 0 and name.split(".")[:2] == ["yazses", "biosignal"]:
            requested.append(name)
        elif level == 0 and name == "yazses" and "biosignal" in (fromlist or ()):
            requested.append("yazses.biosignal")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", spy)
    return requested


# ------------------------------------------------------------------------------ off by default


def test_off_by_default_builds_nothing(tmp_path):
    d = _daemon(tmp_path)
    assert d._build_biosignal_source(d._config) == []
    assert d._biosignal is None and d._biosignal_runner is None


def test_the_default_daemon_never_imports_the_biosignal_package(tmp_path, monkeypatch):
    d = _daemon(tmp_path)
    requested = _biosignal_import_spy(monkeypatch)
    assert d._build_activation_sources(d._config) == []
    assert requested == []


def test_enabled_without_a_source_builds_nothing_and_imports_nothing(tmp_path, monkeypatch, caplog):
    d = _daemon(tmp_path, enabled=True, source="   ")
    requested = _biosignal_import_spy(monkeypatch)
    with caplog.at_level("WARNING", logger=daemon_module.log.name):
        assert d._build_biosignal_source(d._config) == []
    assert requested == []
    assert "no source" in caplog.text


def test_a_source_without_enabled_builds_nothing(tmp_path):
    d = _daemon(tmp_path, enabled=False, source="synthetic")
    assert d._build_biosignal_source(d._config) == []


def test_a_config_without_the_section_is_tolerated(tmp_path):
    d = _daemon(tmp_path)
    assert d._build_biosignal_source(types.SimpleNamespace()) == []


# ------------------------------------------------------------------------------ enabled + synthetic


def test_enabled_synthetic_builds_one_guarded_runner(tmp_path):
    from yazses.biosignal.runner import BiosignalRunner

    d = _daemon(tmp_path, enabled=True, source="synthetic")
    sources = d._build_biosignal_source(d._config)
    assert len(sources) == 1
    source = sources[0]
    assert isinstance(source, _BiosignalGuarded)
    assert isinstance(source._inner, BiosignalRunner)  # it persists its own ledger
    assert d._biosignal is source
    assert d._biosignal_runner is source._inner
    assert source.vocabulary == ("undo",)  # the default intent_map, via __getattr__
    assert d._biosignal_latched is False and d._biosignal_mode == ""


def test_the_runner_saves_its_ledger_under_the_data_dir_at_the_configured_interval(tmp_path):
    d = _daemon(tmp_path, enabled=True, source="synthetic", ledger_autosave_seconds=90.0)
    d._build_biosignal_source(d._config)
    runner = d._biosignal_runner
    assert runner.persists_ledger is True
    assert runner._ledger_path is not None and tmp_path in runner._ledger_path.parents
    assert runner._autosave_s == 90.0


def test_the_source_joins_the_one_list_the_daemon_starts_and_stops(tmp_path):
    """It must ride the `[emg]`/`[facegesture]` seam, not a second list nobody stops."""
    d = _daemon(tmp_path, enabled=True, source="synthetic")
    sources = d._build_activation_sources(d._config)
    assert [type(s) for s in sources] == [_BiosignalGuarded]


def test_the_jaw_clench_intent_vocabulary_follows_the_detectors(tmp_path):
    d = _daemon(tmp_path, enabled=True, source="synthetic", double_blink=False)
    (source,) = d._build_biosignal_source(d._config)
    assert source.vocabulary == ()  # hold-only: no intent labels at all


def test_a_runner_that_cannot_be_built_costs_only_this_source(tmp_path, monkeypatch, caplog):
    d = _daemon(tmp_path, enabled=True, source="synthetic")

    def boom(*a, **k):
        raise RuntimeError("no such board")

    monkeypatch.setattr("yazses.biosignal.runner.build_runner_from_config", boom)
    with caplog.at_level("WARNING", logger=daemon_module.log.name):
        assert d._build_biosignal_source(d._config) == []
    assert "init failed" in caplog.text
    assert d._biosignal is None


def test_a_builder_that_declines_yields_no_source(tmp_path, monkeypatch):
    d = _daemon(tmp_path, enabled=True, source="synthetic")
    monkeypatch.setattr("yazses.biosignal.runner.build_runner_from_config",
                        lambda cfg, cbs, **kw: None)
    assert d._build_biosignal_source(d._config) == []
    assert d._biosignal_runner is None


def test_an_older_runner_without_a_ledger_path_uses_the_persisting_adapter(tmp_path, monkeypatch):
    from yazses.biosignal.cli_impl import BiosignalActivationSource

    d = _daemon(tmp_path, enabled=True, source="synthetic")
    seen: dict = {}
    runner = FakeRunner()
    runner.persists_ledger = False

    def old_builder(cfg, callbacks):  # no ledger_path / autosave_seconds
        seen["called"] = True
        return runner

    monkeypatch.setattr("yazses.biosignal.runner.build_runner_from_config", old_builder)
    (source,) = d._build_biosignal_source(d._config)
    assert seen == {"called": True}
    assert isinstance(source._inner, BiosignalActivationSource)
    assert d._biosignal_runner is runner


def test_a_persisting_runner_is_not_wrapped_in_a_second_persister(tmp_path, monkeypatch):
    """Both writers add the session's counters; two would double-count the record."""
    d = _daemon(tmp_path, enabled=True, source="synthetic")
    kwargs: dict = {}
    runner = FakeRunner()

    def builder(cfg, callbacks, *, ledger_path=None, autosave_seconds=0.0):
        kwargs.update(ledger_path=ledger_path, autosave_seconds=autosave_seconds)
        return runner

    monkeypatch.setattr("yazses.biosignal.runner.build_runner_from_config", builder)
    (source,) = d._build_biosignal_source(d._config)
    assert source._inner is runner
    assert kwargs["autosave_seconds"] == 60.0
    assert tmp_path in kwargs["ledger_path"].parents


def test_a_runner_with_persistence_but_no_public_note_cancelled_still_uses_the_adapter(
        tmp_path, monkeypatch):
    from yazses.biosignal.cli_impl import BiosignalActivationSource

    d = _daemon(tmp_path, enabled=True, source="synthetic")

    class Bare:
        persists_ledger = True
        vocabulary = ()

        def run(self): ...

        def stop(self): ...

        def status(self): return {}

    monkeypatch.setattr("yazses.biosignal.runner.build_runner_from_config",
                        lambda cfg, cbs, **kw: Bare())
    (source,) = d._build_biosignal_source(d._config)
    assert isinstance(source._inner, BiosignalActivationSource)


def test_the_callbacks_are_the_daemons_own(tmp_path, monkeypatch):
    d = _daemon(tmp_path, enabled=True, source="synthetic")
    captured = {}

    def builder(cfg, callbacks, **kw):
        captured["cb"] = callbacks
        return FakeRunner()

    monkeypatch.setattr("yazses.biosignal.runner.build_runner_from_config", builder)
    d._build_biosignal_source(d._config)
    cb = captured["cb"]
    assert cb.on_mode_start == d._biosignal_mode_start
    assert cb.on_mode_end == d._biosignal_mode_end
    assert cb.on_intent == d._biosignal_intent


# ------------------------------------------------------------------------------ speech guard


def _speech_callback(tmp_path, monkeypatch, **bio):
    d = _daemon(tmp_path, enabled=True, source="synthetic", **bio)
    captured = {}

    def builder(cfg, callbacks, **kw):
        captured["cb"] = callbacks
        return FakeRunner()

    monkeypatch.setattr("yazses.biosignal.runner.build_runner_from_config", builder)
    d._build_biosignal_source(d._config)
    return d, captured["cb"].speech_active


def test_the_speech_callback_is_a_speech_guard_over_the_tray_state(tmp_path, monkeypatch):
    from yazses.biosignal.speechguard import SpeechGuard

    d, guard = _speech_callback(tmp_path, monkeypatch)
    assert isinstance(guard, SpeechGuard)
    d._state.state = TrayState.IDLE
    assert guard() is False
    d._state.state = TrayState.RECORDING  # includes a turn the squeeze itself started
    assert guard() is True
    d._state.state = TrayState.MEETING
    assert guard() is True


def test_the_speech_callback_holds_through_a_hangover_after_the_turn_ends(tmp_path, monkeypatch):
    """The jaw's last movements outlast the recording flag; the state read alone misses them."""
    d, guard = _speech_callback(tmp_path, monkeypatch)
    d._state.state = TrayState.RECORDING
    assert guard() is True
    d._state.state = TrayState.TRANSCRIBING
    assert d._biosignal_speaking() is False  # the bare read has already let go ...
    assert guard() is True                    # ... the guard has not (0.5 s hangover)


@pytest.mark.parametrize("state", [s for s in TrayState
                                   if s not in (TrayState.RECORDING, TrayState.MEETING)])
def test_only_recording_and_meeting_count_as_speaking(tmp_path, state):
    d = _daemon(tmp_path)
    d._state.state = state
    assert d._biosignal_speaking() is False


def test_the_speech_callback_is_none_when_the_guard_is_off(tmp_path, monkeypatch):
    _, guard = _speech_callback(tmp_path, monkeypatch, speech_guard=False)
    assert guard is None


def test_without_the_speechguard_module_the_plain_state_read_is_used(tmp_path, monkeypatch):
    d = _daemon(tmp_path)
    monkeypatch.setitem(__import__("sys").modules, "yazses.biosignal.speechguard", None)
    assert d._biosignal_speech_guard() == d._biosignal_speaking


# ------------------------------------------------------------------------------ [activation] policy


def test_policy_is_the_built_in_default_when_activation_is_off(tmp_path):
    d = _daemon(tmp_path)
    d._config.activation.enabled = False
    d._config.activation.confirm_threshold = 0.3
    d._config.activation.reject_floor = 0.1
    assert d._biosignal_policy() == (DEFAULT_CONFIRM_THRESHOLD, DEFAULT_REJECT_FLOOR)


def test_policy_is_the_configured_pair_when_activation_is_on_and_sane(tmp_path):
    d = _daemon(tmp_path)
    d._config.activation.enabled = True
    d._config.activation.confirm_threshold = 0.8
    d._config.activation.reject_floor = 0.4
    assert d._biosignal_policy() == (0.8, 0.4)


@pytest.mark.parametrize("confirm,floor", [(0.4, 0.6), (1.5, 0.5), (0.9, -0.1)])
def test_policy_falls_back_to_the_defaults_when_the_pair_is_not_sane(
        tmp_path, caplog, confirm, floor):
    d = _daemon(tmp_path)
    d._config.activation.enabled = True
    d._config.activation.confirm_threshold = confirm
    d._config.activation.reject_floor = floor
    with caplog.at_level("WARNING", logger=daemon_module.log.name):
        assert d._biosignal_policy() == (DEFAULT_CONFIRM_THRESHOLD, DEFAULT_REJECT_FLOOR)
    assert "using" in caplog.text


def test_an_intent_is_judged_against_the_policy_pair(tmp_path, intent_spy):
    d, *_ = _armed(tmp_path)
    d._config.activation.enabled = True
    d._config.activation.confirm_threshold = 0.8
    d._config.activation.reject_floor = 0.4
    d._biosignal_intent(_intent())
    (call,) = intent_spy.calls
    assert (call["threshold"], call["floor"]) == (0.8, 0.4)
    assert call["vocabulary"] == ("undo",)
    assert call["classify"] == d._gesture_classify
    assert call["dispatch"] == d._gesture_dispatch


# ------------------------------------------------------------------------------ the gate


def test_without_a_global_gate_the_source_is_not_disabled(tmp_path):
    d, *_ = _rig(tmp_path, gate=False)
    assert d._handsfree_safety is None
    assert d._biosignal_check_gate() is True


def test_the_gate_refuses_until_the_source_has_delivered_a_block(tmp_path):
    """A headset that never connects must not hold the global state at 'not ready'."""
    d, runner, safety, *_ = _rig(tmp_path)
    runner.age = None  # no block yet
    assert d._biosignal_check_gate() is False
    assert safety.status().sources == ()  # it never registered
    runner.age = 0.2
    assert d._biosignal_check_gate() is False  # delivered, but nothing has armed it
    assert [s.name for s in safety.status().sources] == [SOURCE]


def test_a_stale_runner_does_not_feed_the_gate(tmp_path):
    d, runner, safety, *_ = _rig(tmp_path)
    runner.age = 5.0
    d._biosignal_check_gate()
    assert d._biosignal_gate_armed is False
    assert safety.status().sources == ()


def test_an_explicit_resume_arms_the_source(tmp_path):
    d, *_ = _armed(tmp_path)
    assert d._biosignal_check_gate() is True


def test_a_gate_that_raises_is_a_refusal(tmp_path):
    d, *_ = _armed(tmp_path)

    def boom(*a, **k):
        raise RuntimeError("gate exploded")

    d._handsfree_safety = types.SimpleNamespace(gate=boom, sample=boom, allow_auto_rearm=boom)
    assert d._biosignal_check_gate() is False


def test_a_runner_whose_status_raises_does_not_feed_the_gate(tmp_path):
    d, runner, safety, *_ = _rig(tmp_path)

    def boom():
        raise RuntimeError("status failed")

    runner.status = boom  # type: ignore[method-assign]
    assert d._biosignal_check_gate() is False
    assert safety.status().sources == ()


def test_a_hold_only_source_re_arms_itself_after_a_stale_disarm(tmp_path):
    """No intent labels -> no accidental-action risk -> the face switch's amendment applies."""
    d, runner, safety, clock, _ = _rig(tmp_path, runner=FakeRunner(vocabulary=()))
    assert d._biosignal_check_gate() is False
    assert safety.resume().ok
    assert d._biosignal_check_gate() is True
    clock.advance(60_000)              # the stream goes quiet for a minute ...
    safety.poll()                      # ... and the watchdog disarms it
    assert safety.gate(SOURCE).allowed is False
    assert d._biosignal_check_gate() is False  # fresh blocks again, run restarts
    for _ in range(20):                # 2 s of unbroken fresh blocks, 100 ms apart (> 1500 ms)
        clock.advance(100)
        d._biosignal_check_gate()
    assert d._biosignal_check_gate() is True


def test_a_source_with_intent_labels_does_not_re_arm_itself(tmp_path):
    d, runner, safety, clock, _ = _rig(tmp_path, runner=FakeRunner(vocabulary=("undo",)))
    assert d._biosignal_check_gate() is False
    assert safety.resume().ok
    clock.advance(60_000)
    safety.poll()
    for _ in range(100):               # 10 s of unbroken fresh blocks
        clock.advance(100)
        d._biosignal_check_gate()
    assert d._biosignal_check_gate() is False


def _transcribing(d, runner, safety, clock, seconds: float):
    """An `_on_hold_end` that holds the runner's thread: no block is read, the watcher ticks."""
    def end() -> None:
        for _ in range(int(seconds * 10)):
            clock.advance(100)
            runner.age += 0.1
            d._biosignal_check_gate()
            safety.poll()
    d._on_hold_end = end


def test_a_long_transcription_does_not_disarm_a_source_with_intent_labels(tmp_path):
    """A squeeze's turn is transcribed on the runner's thread. Blinks and clenches must still
    work after it, without another `yazses handsfree resume`."""
    d, runner, safety, clock, _ = _armed(tmp_path, runner=FakeRunner(vocabulary=("undo",)))
    d._biosignal_mode_start("full_text")
    _transcribing(d, runner, safety, clock, seconds=5.0)
    d._biosignal_mode_end()
    assert d._biosignal_callbacks == 0
    runner.age = 0.1                   # the first block after the callback returns
    assert d._biosignal_check_gate() is True


def test_a_device_that_died_during_the_turn_goes_stale_after_it(tmp_path):
    d, runner, safety, clock, _ = _armed(tmp_path, runner=FakeRunner(vocabulary=("undo",)))
    d._biosignal_mode_start("full_text")
    _transcribing(d, runner, safety, clock, seconds=5.0)
    d._biosignal_mode_end()
    for _ in range(20):                # the runner is free now, and no block ever comes;
        clock.advance(100)             # ticks this short leave no gap, so only the age decides
        runner.age += 0.1
        allowed = d._biosignal_check_gate()
    assert allowed is False
    runner.age = 0.1                   # intent labels: coming back does not re-arm it
    clock.advance(100)
    assert d._biosignal_check_gate() is False


def test_a_pause_during_the_turn_still_holds(tmp_path):
    d, runner, safety, clock, _ = _armed(tmp_path, runner=FakeRunner(vocabulary=("undo",)))
    d._biosignal_mode_start("full_text")
    _transcribing(d, runner, safety, clock, seconds=1.0)
    end = d._on_hold_end
    def paused_end() -> None:
        safety.pause()
        end()
    d._on_hold_end = paused_end
    d._biosignal_mode_end()
    runner.age = 0.1
    assert d._biosignal_check_gate() is False


# ------------------------------------------------------------------------------ squeeze -> mode


def test_a_light_squeeze_starts_dictation_and_ending_it_stops_the_turn(tmp_path):
    d, _, _, _, turns = _armed(tmp_path)
    d._biosignal_mode_start("full_text")
    assert turns.calls == ["dictate"] and d._biosignal_mode == "full_text"
    d._biosignal_mode_end()
    assert turns.calls == ["dictate", "end"] and d._biosignal_mode == ""


def test_a_hard_squeeze_starts_a_command(tmp_path):
    d, _, _, _, turns = _armed(tmp_path)
    d._biosignal_mode_start("command")
    assert turns.calls == ["command"]


def test_a_squeeze_that_gets_harder_upgrades_the_running_turn_in_place(tmp_path):
    d, _, _, _, turns = _armed(tmp_path)
    d._biosignal_mode_start("full_text")
    d._biosignal_mode_start("command")
    assert turns.calls == ["dictate"]  # no second turn
    assert d._biosignal_mode == "command" and d._command_mode is True


def test_a_squeeze_that_gets_lighter_keeps_the_command(tmp_path):
    d, _, _, _, turns = _armed(tmp_path)
    d._biosignal_mode_start("command")
    d._biosignal_mode_start("full_text")
    assert turns.calls == ["command"] and d._biosignal_mode == "command"


@pytest.mark.parametrize("mode", ["", "comand", "dictate", "FULL TEXT"])
def test_a_mistyped_mode_is_refused_not_absorbed_into_the_other_branch(tmp_path, caplog, mode):
    d, _, _, _, turns = _armed(tmp_path)
    with caplog.at_level("WARNING", logger=daemon_module.log.name):
        d._biosignal_mode_start(mode)
    assert turns.calls == []
    assert "not a mode" in caplog.text


def test_mode_names_are_case_insensitive(tmp_path):
    d, _, _, _, turns = _armed(tmp_path)
    d._biosignal_mode_start("  Command ")
    assert turns.calls == ["command"]


def test_mode_end_without_a_turn_does_nothing(tmp_path):
    d, _, _, _, turns = _armed(tmp_path)
    d._biosignal_mode_end()
    assert turns.calls == []


def test_mode_end_before_the_source_was_built_is_a_no_op(tmp_path):
    d = _daemon(tmp_path)
    d._biosignal_mode_end()  # the lock does not exist yet
    d._biosignal_release_held()


# ------------------------------------------------------------------------------ global pause


def test_a_paused_gate_refuses_a_squeeze_and_latches_it(tmp_path):
    d, _, safety, _, turns = _armed(tmp_path)
    safety.pause("paused by the user")
    d._biosignal_mode_start("full_text")
    assert turns.calls == []
    assert d._biosignal_mode == "" and d._biosignal_latched is True


def test_a_squeeze_before_the_first_resume_is_refused(tmp_path):
    d, _, _, _, turns = _rig(tmp_path)
    d._biosignal_mode_start("command")
    assert turns.calls == []


def test_a_held_squeeze_is_released_the_moment_a_pause_lands(tmp_path):
    d, _, safety, _, turns = _armed(tmp_path)
    d._biosignal_mode_start("full_text")
    assert turns.calls == ["dictate"]
    safety.pause("paused by the user")
    assert d._biosignal_check_gate() is False  # what the watcher thread polls
    assert turns.calls == ["dictate", "end"]   # the microphone closes with the pause
    assert d._biosignal_mode == "" and d._biosignal_latched is True


def test_the_release_happens_once_however_often_the_watcher_polls(tmp_path):
    d, _, safety, _, turns = _armed(tmp_path)
    d._biosignal_mode_start("full_text")
    safety.pause("paused by the user")
    for _ in range(5):
        d._biosignal_check_gate()
    assert turns.calls == ["dictate", "end"]


def test_a_released_squeeze_stays_ignored_until_the_signal_relaxes(tmp_path):
    d, _, safety, _, turns = _armed(tmp_path)
    d._biosignal_mode_start("full_text")
    safety.pause("paused by the user")
    d._biosignal_check_gate()
    assert safety.resume().ok

    d._biosignal_mode_start("full_text")   # still squeezing: a strength change, not a new squeeze
    d._biosignal_mode_start("command")
    assert turns.calls == ["dictate", "end"]  # resume mid-squeeze does NOT restart a turn

    d._biosignal_mode_end()                # the muscle relaxes: the latch clears, nothing to end
    assert d._biosignal_latched is False
    assert turns.calls == ["dictate", "end"]

    d._biosignal_mode_start("full_text")   # a fresh squeeze works again
    assert turns.calls == ["dictate", "end", "dictate"]


def test_a_squeeze_refused_while_paused_is_not_started_by_the_resume(tmp_path):
    d, _, safety, _, turns = _armed(tmp_path)
    safety.pause("paused by the user")
    d._biosignal_mode_start("full_text")
    assert safety.resume().ok
    d._biosignal_mode_start("full_text")
    assert turns.calls == []


def test_a_command_squeeze_released_by_a_pause_is_ended_as_a_command_turn(tmp_path):
    d, _, safety, _, turns = _armed(tmp_path)
    d._biosignal_mode_start("command")
    safety.pause("paused by the user")
    d._biosignal_check_gate()
    assert turns.calls == ["command", "end"]


def test_intents_are_ignored_while_the_gate_says_no(tmp_path, intent_spy):
    d, _, safety, _, _ = _armed(tmp_path)
    safety.pause("paused by the user")
    d._biosignal_intent(_intent())
    assert intent_spy.calls == []


def test_intents_run_while_the_gate_says_yes(tmp_path, intent_spy):
    d, *_ = _armed(tmp_path)
    d._biosignal_intent(_intent("undo"))
    assert len(intent_spy.calls) == 1
    assert intent_spy.calls[0]["intent"].label == "undo"


def test_an_intent_is_ignored_while_a_dictation_turn_is_recording(tmp_path, intent_spy):
    """A blink is part of speaking."""
    d, *_ = _armed(tmp_path)
    d._state.state = TrayState.RECORDING
    d._biosignal_intent(_intent())
    assert intent_spy.calls == []


def test_an_intent_with_no_source_built_is_ignored(tmp_path, intent_spy):
    d = _daemon(tmp_path)
    d._biosignal_intent(_intent())
    assert intent_spy.calls == []


def test_an_intent_handler_that_raises_is_contained(tmp_path, monkeypatch, caplog):
    d, *_ = _armed(tmp_path)

    def boom(*a, **k):
        raise RuntimeError("grammar exploded")

    monkeypatch.setattr("yazses.activation.pipeline.handle_intent", boom)
    with caplog.at_level("WARNING", logger=daemon_module.log.name):
        d._biosignal_intent(_intent())  # must not raise into the runner's thread
    assert "raised; ignored" in caplog.text


# ------------------------------------------------------------------------------ handsfree IPC


def _request(action: str) -> Request:
    return Request("handsfree", {"action": action})


def test_handsfree_resume_releases_the_governor(tmp_path):
    d, runner, _, _, _ = _rig(tmp_path, gate=False)
    reply = Daemon._handle_handsfree(d, _request("resume"))
    assert runner.released == 1
    assert isinstance(reply, dict)


def test_handsfree_resume_releases_the_governor_and_arms_the_gate(tmp_path):
    d, runner, safety, _, _ = _rig(tmp_path)
    reply = Daemon._handle_handsfree(d, _request("resume"))
    assert runner.released == 1
    assert reply["ok"] is True
    assert SOURCE in reply["scope"]
    assert safety.gate(SOURCE).allowed is True


def test_handsfree_resume_leaves_the_governor_alone_when_biosignal_is_off(tmp_path):
    d = _daemon(tmp_path)
    runner = FakeRunner()
    d._biosignal_runner = runner  # present, but the source was never built
    assert d._biosignal is None
    Daemon._handle_handsfree(d, _request("resume"))
    assert runner.released == 0


def test_a_failing_governor_release_does_not_break_resume(tmp_path):
    d, runner, safety, _, _ = _rig(tmp_path)

    def boom():
        raise RuntimeError("governor exploded")

    runner.governor_release = boom  # type: ignore[method-assign]
    reply = Daemon._handle_handsfree(d, _request("resume"))
    assert reply["ok"] is True


def test_handsfree_pause_releases_a_held_squeeze_at_once(tmp_path):
    d, _, safety, _, turns = _armed(tmp_path)
    d._biosignal_mode_start("full_text")
    reply = Daemon._handle_handsfree(d, _request("pause"))
    assert reply["ok"] is True
    assert turns.calls == ["dictate", "end"]
    assert d._biosignal_latched is True
    assert safety.gate(SOURCE).allowed is False


def test_handsfree_pause_without_the_gate_does_not_touch_the_squeeze(tmp_path):
    d, _, _, _, turns = _rig(tmp_path, gate=False)
    d._biosignal_mode_start("full_text")
    reply = Daemon._handle_handsfree(d, _request("pause"))
    assert reply["ok"] is False  # nothing to pause: the gate is off
    assert turns.calls == ["dictate"]


# ------------------------------------------------------------------------------ note_cancelled


def test_a_cancel_is_routed_to_the_runner(tmp_path):
    d, runner, *_ = _rig(tmp_path)
    d._biosignal_note_cancelled()
    assert runner.cancelled == 1


def test_a_cancel_falls_back_to_the_adapter_for_an_older_runner(tmp_path):
    d, *_ = _rig(tmp_path)
    counted = []
    d._biosignal_runner = types.SimpleNamespace()  # no note_cancelled of its own
    d._biosignal = types.SimpleNamespace(note_cancelled=lambda: counted.append(1))
    d._biosignal_note_cancelled()
    assert counted == [1]


def test_a_cancel_with_nobody_to_count_it_is_a_no_op(tmp_path):
    d = _daemon(tmp_path)
    d._biosignal_note_cancelled()


def test_a_failing_cancel_is_contained(tmp_path):
    d, runner, *_ = _rig(tmp_path)

    def boom(kind=None):
        raise RuntimeError("ledger exploded")

    runner.note_cancelled = boom  # type: ignore[method-assign]
    d._biosignal_note_cancelled()


def test_only_a_spoken_undo_is_counted_and_the_switchs_own_undo_cannot_cancel_itself():
    """Pins the call site: guarded by the action and by the source existing, and the
    switch's own undo goes through `_biosignal_intent`, which never calls it."""
    source = inspect.getsource(Daemon)
    assert re.search(
        r'if intent\.action == "undo" and getattr\(self, "_biosignal", None\) is not None:\s+'
        r"self\._biosignal_note_cancelled\(\)", source)
    assert "_biosignal_note_cancelled" not in inspect.getsource(Daemon._biosignal_intent)


# ------------------------------------------------------------------------------ the wrapper


def test_the_wrapper_polls_the_gate_while_the_source_runs_and_stops_with_it(monkeypatch):
    monkeypatch.setattr(daemon_module, "_BIOSIGNAL_GUARD_POLL_S", 0.005)
    ticked = threading.Event()
    count = []

    def tick():
        count.append(1)
        if len(count) >= 3:
            ticked.set()

    class Inner:
        vocabulary = ("undo",)

        def __init__(self) -> None:
            self.release = threading.Event()
            self.stopped = False

        def run(self) -> None:
            self.release.wait(5)

        def stop(self) -> None:
            self.stopped = True
            self.release.set()

    inner = Inner()
    guarded = _BiosignalGuarded(inner, tick)
    thread = threading.Thread(target=guarded.run, daemon=True)
    thread.start()
    assert ticked.wait(5), "the watcher never polled the gate"
    assert guarded.vocabulary == ("undo",)  # every other attribute is the wrapped source's
    guarded.stop()
    thread.join(5)
    assert not thread.is_alive()
    assert inner.stopped is True
    settled = len(count)
    time.sleep(0.05)
    assert len(count) == settled  # the watcher is gone with the source


def test_a_tick_that_raises_does_not_kill_the_watcher(monkeypatch):
    monkeypatch.setattr(daemon_module, "_BIOSIGNAL_GUARD_POLL_S", 0.005)
    done = threading.Event()
    calls = []

    def tick():
        calls.append(1)
        if len(calls) >= 3:
            done.set()
        raise RuntimeError("tick failed")

    class Inner:
        def run(self) -> None:
            done.wait(5)

        def stop(self) -> None:
            done.set()

    guarded = _BiosignalGuarded(Inner(), tick)
    guarded.run()
    assert len(calls) >= 3


# ------------------------------------------------------------------------------ modality


def test_a_configured_source_is_listed_among_the_available_modalities(tmp_path, caplog):
    d = _daemon(tmp_path, enabled=True, source="synthetic")
    d._config.modality.enabled = True
    d._config.modality.preset = "hands-free"
    with caplog.at_level("INFO", logger=daemon_module.log.name):
        roles = d._resolve_modality_roles(d._config)
    assert roles.get("command") == "emg"  # the squeeze takes the command role like an EMG band


def test_an_unconfigured_biosignal_is_not_listed_among_the_modalities(tmp_path):
    d = _daemon(tmp_path, enabled=True, source="")
    d._config.modality.enabled = True
    d._config.modality.preset = "hands-free"
    roles = d._resolve_modality_roles(d._config)
    assert "emg" not in roles.values()
