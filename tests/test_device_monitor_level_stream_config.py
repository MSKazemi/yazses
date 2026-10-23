"""The device monitor's three level-stream timings are `[audio]` settings.

Wave 2 (`3df68e47`) taught the device monitor to re-scan while a hands-free level stream
(Vocal Morse, the Mouth-Sound Switch, the Vocal Joystick) holds the microphone, with three
module constants: a full re-scan every 30 s, a 600 s backstop for a user mid-gesture, and a
2 s window in which audio counts as "still arriving". They are now
`[audio] level_stream_rescan_s`, `level_stream_in_use_max_s` and `level_stream_fresh_s`.

Pinned here, offline (no audio library, no thread, no sleep):

* the defaults are the old constants, so an existing install behaves exactly as before;
* a configured value changes the plan (`plan_device_poll`, `DeviceMonitor`) and the
  runners' "in use" verdict, and the daemon threads each key to the place that uses it;
* an out-of-range, non-finite or mistyped value falls back to the default with a
  `ConfigProblem`, the way every bounded key does -- loading never raises (#52).
"""
from __future__ import annotations

import ast
import inspect
import math
import textwrap
import types
from pathlib import Path

import numpy as np
import pytest

from tests.pointer_fake import FakePointerSink
from yazses.audio.device_monitor import (
    CYCLE,
    ENGAGED_AUDIO_FRESH_S,
    ENGAGED_DEFER_MAX_S,
    LEVEL_STREAM_RESCAN_S,
    PEEK,
    DeviceMonitor,
    plan_device_poll,
)
from yazses.config import AudioConfig, load_config_checked
from yazses.configcheck import ConfigProblem, build_section

KEYS = ("level_stream_rescan_s", "level_stream_in_use_max_s", "level_stream_fresh_s")


class Clock:
    """A monotonic clock moved by hand."""

    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def _audio(raw: dict) -> tuple[AudioConfig, list[ConfigProblem]]:
    problems: list[ConfigProblem] = []
    return build_section(AudioConfig, raw, "audio", problems), problems


# --------------------------------------------------------------------------- #
# Defaults: nothing changes for an existing install
# --------------------------------------------------------------------------- #
def test_the_defaults_are_the_constants_wave_2_shipped():
    audio = AudioConfig()
    assert audio.level_stream_rescan_s == LEVEL_STREAM_RESCAN_S == 30.0
    assert audio.level_stream_in_use_max_s == ENGAGED_DEFER_MAX_S == 600.0
    assert audio.level_stream_fresh_s == ENGAGED_AUDIO_FRESH_S == 2.0


def test_an_empty_audio_section_loads_the_defaults_with_no_problem():
    audio, problems = _audio({})
    assert problems == []
    assert (audio.level_stream_rescan_s, audio.level_stream_in_use_max_s,
            audio.level_stream_fresh_s) == (30.0, 600.0, 2.0)


def test_the_shipped_defaults_sit_inside_their_own_bounds():
    """A default outside its declared range would be refused the moment a user wrote it."""
    import dataclasses

    from yazses.configcheck import out_of_bounds

    fields = {f.name: f for f in dataclasses.fields(AudioConfig)}
    for key in KEYS:
        f = fields[key]
        assert out_of_bounds(f, f.default) is None, key
        assert {"min", "max"} <= set(f.metadata), f"{key} must declare its range"


# --------------------------------------------------------------------------- #
# A configured value is honoured
# --------------------------------------------------------------------------- #
def test_custom_values_load_from_a_file(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        "[audio]\n"
        "level_stream_rescan_s = 10\n"  # an int is a valid float
        "level_stream_in_use_max_s = 120.0\n"
        "level_stream_fresh_s = 0.75\n",
        encoding="utf-8",
    )
    loaded = load_config_checked(path)
    audio = loaded.config.audio
    assert [p for p in loaded.problems if p.section == "audio"] == []
    assert audio.level_stream_rescan_s == 10.0
    assert isinstance(audio.level_stream_rescan_s, float)
    assert audio.level_stream_in_use_max_s == 120.0
    assert audio.level_stream_fresh_s == 0.75


def _plan(**kw) -> str:
    base = dict(
        recording=False, streams_open=True, engaged=False, now=10.0, last_rescan_at=0.0,
        engaged_since=None, rebind_pending=False, can_peek=True,
    )
    base.update(kw)
    return plan_device_poll(**base)


def test_a_shorter_rescan_interval_makes_the_cycle_due_sooner():
    assert _plan(now=10.0) == PEEK  # the default: not due until 30 s
    assert _plan(now=10.0, rescan_every_s=10.0) == CYCLE
    assert _plan(now=40.0, rescan_every_s=60.0) == PEEK  # a longer one waits longer


def test_a_shorter_backstop_ends_the_deferral_sooner():
    engaged = dict(engaged=True, engaged_since=0.0, now=120.0)
    assert _plan(**engaged) == PEEK  # the default backstop is 600 s
    assert _plan(**engaged, max_defer_s=120.0) == CYCLE


class _Stream:
    """A minimal `LevelStreamOwner`: open, optionally in use, records its cycles."""

    def __init__(self, engaged: bool = False) -> None:
        self.mic_open = True
        self.engaged = engaged
        self.cycles = 0

    @property
    def mic_engaged(self) -> bool:
        return self.mic_open and self.engaged

    def release_mic_for_rescan(self) -> bool:
        self.mic_open = False
        return True

    def reacquire_mic_after_rescan(self):
        self.mic_open = True
        self.cycles += 1
        return True, ""


def _monitor(stream: _Stream, clock: Clock, **kw) -> tuple[DeviceMonitor, list[str]]:
    reinits: list[str] = []

    def poll() -> str:
        assert not stream.mic_open, "PortAudio re-initialised under an open stream"
        reinits.append("reinit")
        return "MicA"

    monitor = DeviceMonitor(
        poll_fn=poll,
        is_idle=lambda: not stream.mic_open,
        on_change=lambda prev, cur: None,
        level_streams=lambda: [stream],
        recording=lambda: False,
        peek_fn=lambda: "MicA",
        clock=clock,
        **kw,
    )
    return monitor, reinits


def test_the_monitor_uses_the_configured_rescan_interval():
    clock, stream = Clock(), _Stream()
    monitor, reinits = _monitor(stream, clock, rescan_every_s=12.0)
    clock.t = 11.9
    monitor.poll_once()
    assert monitor.last_action == PEEK and reinits == []
    clock.t = 12.0
    monitor.poll_once()
    assert monitor.last_action == CYCLE and reinits == ["reinit"] and stream.cycles == 1


def test_the_monitor_uses_the_configured_backstop():
    clock, stream = Clock(), _Stream(engaged=True)
    monitor, reinits = _monitor(stream, clock, rescan_every_s=10.0, max_defer_s=30.0)
    clock.t = 10.0
    monitor.poll_once()  # due, but in use: engaged_since starts now
    assert monitor.last_action == PEEK
    clock.t = 39.9
    monitor.poll_once()
    assert monitor.last_action == PEEK and reinits == []
    clock.t = 40.0
    monitor.poll_once()
    assert monitor.last_action == CYCLE and reinits == ["reinit"]


# ---- The fresh window reaches every runner ------------------------------------------------
class FakeRecorder:
    def __init__(self, on_chunk) -> None:
        self.on_chunk = on_chunk
        self.started = 0
        self.stopped = 0

    def start(self) -> None:
        self.started += 1

    def stop(self):
        self.stopped += 1
        return np.zeros(0, dtype=np.float32)


def _morse(clock: Clock, **kw):
    from yazses.morsevox.runtime import build_morse_runner

    made: list[FakeRecorder] = []

    def factory(on_chunk):
        made.append(FakeRecorder(on_chunk))
        return made[-1]

    cfg = types.SimpleNamespace(enabled=True, dot_max_ms=200.0, letter_gap_ms=600.0,
                                word_gap_ms=1400.0, entry_hum_s=1.5, exit_silence_s=3.0)
    runner, notes = build_morse_runner(
        cfg, threshold=0.02, recorder_factory=factory, inject=lambda text: None,
        clock=clock, thread=False, **kw,
    )
    assert runner is not None, notes
    return runner, made


@pytest.mark.parametrize(("fresh_s", "engaged_after_3s"), [(None, False), (5.0, True)])
def test_morse_mode_is_in_use_for_the_configured_window(fresh_s, engaged_after_3s):
    clock = Clock(100.0)
    kw = {} if fresh_s is None else {"engaged_fresh_s": fresh_s}
    runner, made = _morse(clock, **kw)
    runner.start()
    assert runner.enter_by_command() == (True, "")
    made[0].on_chunk(np.zeros(320, dtype=np.float32))
    assert runner.mic_engaged is True
    clock.t += 3.0  # no audio since: past the default 2 s, inside a configured 5 s
    assert runner.mic_engaged is engaged_after_3s


def test_the_vocal_joystick_builder_hands_the_runner_the_window():
    from yazses.vocaljoystick.runtime import build_vocaljoystick

    cfg = types.SimpleNamespace(enabled=True)
    built = build_vocaljoystick(cfg, pointer_factory=FakePointerSink,
                                recorder_factory=FakeRecorder, thread=False)
    assert built.runner is not None
    assert built.runner._engaged_fresh_s == ENGAGED_AUDIO_FRESH_S
    built = build_vocaljoystick(cfg, pointer_factory=FakePointerSink,
                                recorder_factory=FakeRecorder, thread=False,
                                engaged_fresh_s=7.5)
    assert built.runner._engaged_fresh_s == 7.5


def test_a_held_vowel_is_in_use_for_the_configured_window():
    from tests.synthetic_voice import PETERSON_BARNEY_MALE, vowel
    from yazses.vocaljoystick.runtime import VocalJoystickRunner, VocalJoystickRuntime

    clock = Clock(50.0)
    made: list[FakeRecorder] = []

    def factory(on_chunk):
        made.append(FakeRecorder(on_chunk))
        return made[-1]

    runner = VocalJoystickRunner(FakePointerSink(), recorder_factory=factory, thread=False,
                                 clock=clock, engaged_fresh_s=5.0)
    runtime = VocalJoystickRuntime(runner=runner)
    runtime.toggle("resume", [], [])
    audio = vowel(PETERSON_BARNEY_MALE["i"], 0.6)
    for i in range(0, audio.size, 512):
        made[0].on_chunk(audio[i:i + 512])
    assert runtime.mic_engaged is True
    clock.t += 3.0  # past the default 2 s, inside the configured 5 s
    assert runtime.mic_engaged is True
    clock.t += 3.0  # now past 5 s too
    assert runtime.mic_engaged is False


def test_the_mouth_switch_builder_hands_the_runner_the_window():
    from yazses.commands.grammar import classify
    from yazses.config import Config
    from yazses.mouthswitch.runtime import build_mouthswitch

    cfg = Config().mouthswitch
    cfg.enabled = True
    common = dict(
        pointer_factory=FakePointerSink,
        recorder_factory=FakeRecorder,
        run_command=lambda phrase: None,
        classify=lambda phrase: classify(phrase, "default", language="en"),
        highlight_available=True,
        thread=False,
    )
    built = build_mouthswitch(cfg, **common)
    assert built.runner is not None, built
    assert built.runner._engaged_fresh_s == ENGAGED_AUDIO_FRESH_S
    built = build_mouthswitch(cfg, **common, engaged_fresh_s=9.0)
    assert built.runner._engaged_fresh_s == 9.0


# ---- The daemon threads each key to its consumer -------------------------------------------
def _keywords(method, callee: str) -> dict[str, str]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(method)))
    call = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == callee
    )
    return {kw.arg: ast.unparse(kw.value) for kw in call.keywords if kw.arg}


def test_the_daemon_hands_the_monitor_the_configured_timings():
    from yazses.core.daemon import Daemon

    keywords = _keywords(Daemon._build_pipeline, "DeviceMonitor")
    assert keywords["rescan_every_s"] == "cfg.audio.level_stream_rescan_s"
    assert keywords["max_defer_s"] == "cfg.audio.level_stream_in_use_max_s"


@pytest.mark.parametrize(("method", "callee"), [
    ("_build_morsevox", "build_morse_runner"),
    ("_build_vocaljoystick", "build_vocaljoystick"),
    ("_build_mouthswitch", "build_mouthswitch"),
])
def test_the_daemon_hands_every_runner_the_configured_window(method, callee):
    from yazses.core.daemon import Daemon

    keywords = _keywords(getattr(Daemon, method), callee)
    assert keywords["engaged_fresh_s"] == "cfg.audio.level_stream_fresh_s"


# --------------------------------------------------------------------------- #
# A bad value is repaired or refused like every bounded key, never a crash
# --------------------------------------------------------------------------- #
DEFAULTS = {"level_stream_rescan_s": 30.0, "level_stream_in_use_max_s": 600.0,
            "level_stream_fresh_s": 2.0}


@pytest.mark.parametrize(("key", "value"), [
    ("level_stream_rescan_s", 0),         # would cycle the streams on every poll
    ("level_stream_rescan_s", 4.9),       # below the floor
    ("level_stream_rescan_s", 3601),      # above the ceiling
    ("level_stream_rescan_s", -30),       # negative: impossible for a duration
    ("level_stream_in_use_max_s", 9.9),
    ("level_stream_in_use_max_s", 86400),
    ("level_stream_fresh_s", 0),          # nothing would ever count as in use
    ("level_stream_fresh_s", 0.49),
    ("level_stream_fresh_s", 61),
    ("level_stream_fresh_s", True),       # a bool is not a number
    ("level_stream_fresh_s", "soon"),     # neither is this text
    ("level_stream_rescan_s", math.inf),  # non-finite: refused by the float coercion
    ("level_stream_in_use_max_s", math.nan),
])
def test_an_unusable_value_falls_back_to_the_default_and_says_so(key, value):
    audio, problems = _audio({key: value})
    assert getattr(audio, key) == DEFAULTS[key]
    (problem,) = [p for p in problems if p.key == key]
    assert problem.section == "audio" and problem.repaired is False
    assert "using the default instead" in problem.detail


def test_a_quoted_number_in_range_is_repaired_and_used():
    audio, problems = _audio({"level_stream_rescan_s": "45"})
    assert audio.level_stream_rescan_s == 45.0
    (problem,) = problems
    assert problem.key == "level_stream_rescan_s" and problem.repaired is True


def test_one_bad_key_does_not_disturb_its_neighbours():
    audio, problems = _audio({"level_stream_rescan_s": 15, "level_stream_fresh_s": -1,
                              "level_stream_in_use_max_s": 90})
    assert audio.level_stream_rescan_s == 15.0
    assert audio.level_stream_in_use_max_s == 90.0
    assert audio.level_stream_fresh_s == 2.0
    assert [p.key for p in problems] == ["level_stream_fresh_s"]


@pytest.mark.parametrize("literal", ["inf", "-inf", "nan", "1e999", '"30"', "[1, 2]",
                                     "{ a = 1 }", "true", '""'])
def test_loading_a_file_with_any_value_never_raises(tmp_path: Path, literal: str):
    """The totality contract (#52) that `fuzz/fuzz_config.py` attacks, on these keys."""
    path = tmp_path / "config.toml"
    path.write_text(
        "[audio]\n" + "".join(f"{key} = {literal}\n" for key in KEYS), encoding="utf-8"
    )
    audio = load_config_checked(path).config.audio
    for key in KEYS:
        value = getattr(audio, key)
        assert isinstance(value, float) and math.isfinite(value), (key, value)
        lo, hi = {"level_stream_rescan_s": (5.0, 3600.0),
                  "level_stream_in_use_max_s": (10.0, 3600.0),
                  "level_stream_fresh_s": (0.5, 60.0)}[key]
        assert lo <= value <= hi, (key, value)
