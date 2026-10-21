"""The Vocal Joystick is reachable -- armed only by the existing hands-free toggle (#164).

WIRE-VOCALJOYSTICK-001. Four claims:

* **A default install is unchanged.** `[vocaljoystick]` ships off, so the daemon imports nothing
  from `yazses.vocaljoystick`, asks for no pointer sink, opens no microphone, and the
  `handsfree` IPC replies exactly as it did before.
* **The microphone is open only while armed.** Enabling the feature builds a runner but opens
  nothing; `yazses handsfree resume` opens the stream, `handsfree pause` (and so the spoken stop
  phrase, which reuses it) closes it, and so does a pause from the global gate, which it only
  reads. While it is open the device monitor does not reinit PortAudio under it.
* **A held vowel moves the pointer the way the mapping says** -- "eee" up-left -- and a held
  pitch jump clicks once.
* **The guards hold on what they exist for** (AGENTS.md rule 9): running speech, a quiet voice,
  noise and a one-frame pitch spike move and click nothing, and nothing is steered while
  dictation is busy. All of it on synthetic signals (`tests/synthetic_voice.py`), the only
  signals these thresholds have been tuned on.
"""
from __future__ import annotations

import dataclasses
import time

import numpy as np
import pytest

from tests.pointer_fake import FakePointerSink, PointerActionKind
from tests.synthetic_voice import PETERSON_BARNEY_MALE, silence, vowel, white_noise
from tests.test_dormant_features_stay_unimported import started, tripwire  # noqa: F401
from yazses.config import Config
from yazses.ipc.protocol import Request
from yazses.platform import get_platform
from yazses.platform.base import TrayState
from yazses.system.features import feature_status, unwired_slugs


class FakeRecorder:
    """Stands in for `AudioRecorder`: records start/stop, and pushes chunks on request."""

    instances: list[FakeRecorder] = []

    def __init__(self, on_chunk) -> None:
        self.on_chunk = on_chunk
        self.started = 0
        self.stopped = 0
        FakeRecorder.instances.append(self)

    @property
    def open(self) -> bool:
        return self.started > self.stopped

    def start(self) -> None:
        self.started += 1

    def stop(self):
        self.stopped += 1
        return np.zeros(0, dtype=np.float32)

    def push(self, audio: np.ndarray, chunk: int = 512) -> None:
        for i in range(0, audio.size, chunk):
            self.on_chunk(audio[i:i + chunk])


def _runner(sink=None, **kwargs):
    from yazses.vocaljoystick.runtime import VocalJoystickRunner

    made: list[FakeRecorder] = []

    def factory(on_chunk):
        rec = FakeRecorder(on_chunk)
        made.append(rec)
        return rec

    sink = sink or FakePointerSink()
    runner = VocalJoystickRunner(sink, recorder_factory=factory, thread=False, **kwargs)
    return runner, sink, made


def _moves(sink: FakePointerSink):
    return [a for a in sink.actions if a.kind is PointerActionKind.MOVE_RELATIVE]


def _clicks(sink: FakePointerSink):
    return [a for a in sink.actions if a.kind is PointerActionKind.BUTTON_PRESS]


def _i(seconds: float, **kw) -> np.ndarray:
    return vowel(PETERSON_BARNEY_MALE["i"], seconds, **kw)


# --------------------------------------------------------------------------- #
# Registry honesty
# --------------------------------------------------------------------------- #
def test_vocaljoystick_is_no_longer_advertised_as_unwired():
    assert "vocaljoystick" not in unwired_slugs()
    feature = next(f for f in feature_status(Config()) if f.slug == "vocaljoystick")
    assert feature.wired is True


def test_the_registry_no_longer_claims_eee_moves_the_cursor_straight_up():
    from yazses.system.features import _EXAMPLES, _registry
    from yazses.vocaljoystick.control import vowel_to_direction

    assert vowel_to_direction(PETERSON_BARNEY_MALE["i"][:2]) == "nw"
    definition = next(d for d in _registry() if d.slug == "vocaljoystick")
    assert "'eee' up-left" in definition.why
    assert "'eee' up," not in definition.why
    assert "up and to the left" in _EXAMPLES["vocaljoystick"]


# --------------------------------------------------------------------------- #
# A default install is unchanged
# --------------------------------------------------------------------------- #
def test_a_default_daemon_never_imports_the_vocal_joystick(tripwire, started):  # noqa: F811
    daemon = started(Config())
    assert "vocaljoystick" not in tripwire.packages()
    assert daemon._vocaljoystick is None


def test_an_enabled_daemon_imports_and_builds_it(tripwire, started, monkeypatch):  # noqa: F811
    """The positive control for the test above: the tripwire does see the import."""
    import yazses.core.daemon as daemon_mod

    sink = FakePointerSink()
    monkeypatch.setattr(daemon_mod, "AudioRecorder", lambda **kw: FakeRecorder(kw["on_chunk"]))
    cfg = Config()
    cfg.vocaljoystick.enabled = True
    daemon = started(cfg, pipeline=False)
    daemon._platform = dataclasses.replace(daemon._platform, pointer_factory=lambda: sink)
    runtime = daemon._build_vocaljoystick(cfg)
    assert "vocaljoystick" in tripwire.packages()
    assert runtime is not None and runtime.available


def _daemon(cfg: Config | None = None, sink=None):
    from yazses.core.daemon import Daemon

    platform = get_platform()
    if sink is not None:
        platform = dataclasses.replace(platform, pointer_factory=lambda: sink)
    return Daemon(config=cfg or Config(), platform=platform)


def test_the_default_handsfree_replies_are_byte_for_byte_what_they_were():
    daemon = _daemon()
    daemon._vocaljoystick = daemon._build_vocaljoystick(Config())
    assert daemon._vocaljoystick is None
    assert daemon._handle_handsfree(Request("handsfree", {"action": "pause"})) == {
        "ok": False,
        "reason": "nothing hands-free is running, and the global stop is off "
        "(`[handsfree_safety] enabled = false`)",
    }
    assert daemon._handle_handsfree(Request("handsfree", {"action": "resume"})) == {
        "ok": False, "reason": "nothing hands-free is running",
    }


def test_a_default_daemon_asks_for_no_pointer_sink():
    asked: list[int] = []
    daemon = _daemon()
    daemon._platform = dataclasses.replace(
        get_platform(), pointer_factory=lambda: asked.append(1)  # type: ignore[arg-type,return-value]
    )
    assert daemon._build_vocaljoystick(Config()) is None
    assert asked == []


# --------------------------------------------------------------------------- #
# The microphone is open only while armed -- through the existing toggle
# --------------------------------------------------------------------------- #
@pytest.fixture
def armed_daemon(monkeypatch):
    import yazses.core.daemon as daemon_mod

    FakeRecorder.instances.clear()
    monkeypatch.setattr(daemon_mod, "AudioRecorder", lambda **kw: FakeRecorder(kw["on_chunk"]))
    sink = FakePointerSink()
    cfg = Config()
    cfg.vocaljoystick.enabled = True
    daemon = _daemon(cfg, sink)
    daemon._vocaljoystick = daemon._build_vocaljoystick(cfg)
    daemon._state.state = TrayState.IDLE
    yield daemon, sink
    daemon._vocaljoystick.stop()


def _wait_for(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_enabling_it_opens_no_microphone(armed_daemon):
    daemon, sink = armed_daemon
    assert daemon._vocaljoystick.available
    assert FakeRecorder.instances == []  # built, never opened
    assert sink.actions == []


def test_handsfree_resume_opens_the_microphone_and_pause_closes_it(armed_daemon):
    daemon, sink = armed_daemon
    reply = daemon._handle_handsfree(Request("handsfree", {"action": "resume"}))
    assert reply == {"ok": True, "scope": ["Vocal Joystick"]}
    (rec,) = FakeRecorder.instances
    assert rec.open

    rec.push(_i(0.6))  # a held "eee", through the real worker thread
    assert _wait_for(lambda: len(_moves(sink)) > 10)
    moves = _moves(sink)
    assert all(m.x < 0 and m.y < 0 for m in moves)  # up-left, as the mapping says

    reply = daemon._handle_handsfree(Request("handsfree", {"action": "pause"}))
    assert reply == {"ok": True, "scope": ["Vocal Joystick"]}
    assert not rec.open


def test_the_spoken_stop_phrase_closes_the_microphone(armed_daemon):
    daemon, _sink = armed_daemon
    daemon._config.handsfree_safety.stop_phrase = "stop pointer"  # opt-in; ships empty
    daemon._handle_handsfree(Request("handsfree", {"action": "resume"}))
    (rec,) = FakeRecorder.instances
    assert daemon._try_voice_stop("stop pointer", {}) is True
    assert not rec.open


def test_a_pause_from_the_global_gate_closes_the_microphone(monkeypatch):
    """A face switch's `pause_pointer` pauses the gate directly, not through the IPC."""
    import yazses.core.daemon as daemon_mod

    FakeRecorder.instances.clear()
    monkeypatch.setattr(daemon_mod, "AudioRecorder", lambda **kw: FakeRecorder(kw["on_chunk"]))
    sink = FakePointerSink()
    cfg = Config()
    cfg.vocaljoystick.enabled = True
    cfg.handsfree_safety.enabled = True
    daemon = _daemon(cfg, sink)
    daemon._handsfree_safety = daemon._build_handsfree_safety(cfg)
    daemon._vocaljoystick = daemon._build_vocaljoystick(cfg)
    daemon._state.state = TrayState.IDLE
    try:
        reply = daemon._handle_handsfree(Request("handsfree", {"action": "resume"}))
        assert reply["ok"] is True, reply
        (rec,) = FakeRecorder.instances
        rec.push(_i(0.4))
        assert _wait_for(lambda: len(_moves(sink)) > 0)
        daemon._handsfree_safety.pause("face switch")
        rec.push(_i(0.1))
        assert _wait_for(lambda: not rec.open)
        before = len(_moves(sink))
        rec.push(_i(0.4))
        time.sleep(0.1)
        assert len(_moves(sink)) == before
        # It only *reads* the gate: it is no source, so a closed joystick can never leave a
        # stale one behind that reports the whole hands-free system as faulted.
        status = daemon._handsfree_safety.status()
        assert status.source("vocaljoystick") is None
        assert "stale" not in status.reason
        # And the explicit resume brings it back.
        assert daemon._handle_handsfree(Request("handsfree", {"action": "resume"}))["ok"] is True
        assert FakeRecorder.instances[-1].open
    finally:
        daemon._vocaljoystick.stop()


def test_pausing_a_joystick_that_was_never_started_claims_nothing(armed_daemon):
    """With the gate off and nothing armed, `handsfree pause` must not report a pause."""
    daemon, _sink = armed_daemon
    assert daemon._handle_handsfree(Request("handsfree", {"action": "pause"})) == {
        "ok": False,
        "reason": "nothing hands-free is running, and the global stop is off "
        "(`[handsfree_safety] enabled = false`)",
    }


def test_the_device_monitor_never_reinits_portaudio_under_the_open_stream(armed_daemon):
    """The joystick keeps the daemon IDLE while its stream is open; a reinit would kill it."""
    daemon, _sink = armed_daemon
    assert daemon._audio_idle() is True
    daemon._handle_handsfree(Request("handsfree", {"action": "resume"}))
    assert daemon._audio_idle() is False
    daemon._handle_handsfree(Request("handsfree", {"action": "pause"}))
    assert daemon._audio_idle() is True


def test_a_fault_is_told_to_the_user_once(monkeypatch):
    told: list[str] = []
    runner, sink, made = _runner(on_fault=told.append)
    runner.start()
    sink.fail_with()
    made[0].push(_i(1.0))
    assert len(told) == 1 and told[0].startswith("pointer output failed")


def test_the_daemon_wires_the_fault_to_a_notification(armed_daemon, monkeypatch):
    import yazses.system.notify as notify_mod

    told: list[tuple[str, str]] = []
    monkeypatch.setattr(notify_mod, "notify", lambda title, body, **kw: told.append((title, body)))
    daemon, sink = armed_daemon
    runner = daemon._vocaljoystick.runner
    runner._use_thread = False  # drive the chunk inline
    assert runner.start() == (True, "")
    sink.fail_with()
    FakeRecorder.instances[-1].push(_i(1.0))
    assert len(told) == 1
    assert "Vocal Joystick" in told[0][0] and "handsfree resume" in told[0][1]


def test_shutdown_closes_the_stream_and_releases_the_sink(armed_daemon):
    daemon, sink = armed_daemon
    daemon._handle_handsfree(Request("handsfree", {"action": "resume"}))
    (rec,) = FakeRecorder.instances
    daemon._vocaljoystick.stop()
    assert not rec.open and sink.closed


def test_a_platform_without_a_pointer_says_so_on_resume(monkeypatch):
    cfg = Config()
    cfg.vocaljoystick.enabled = True
    daemon = _daemon(cfg)
    daemon._platform = dataclasses.replace(get_platform(), pointer_factory=None)
    daemon._vocaljoystick = daemon._build_vocaljoystick(cfg)
    reply = daemon._handle_handsfree(Request("handsfree", {"action": "resume"}))
    assert reply["ok"] is False
    assert "no pointer backend" in str(reply["reason"])


# --------------------------------------------------------------------------- #
# Motion and click, end to end through the runner
# --------------------------------------------------------------------------- #
def test_a_held_eee_moves_up_left_after_the_sustain_threshold():
    from yazses.vocaljoystick.drive import SUSTAIN_FRAMES

    runner, sink, made = _runner()
    assert runner.start() == (True, "")
    (rec,) = made
    rec.push(_i(1.0))
    moves = _moves(sink)
    # ~97 frames of one second; motion starts only once the direction has held.
    assert 50 < len(moves) <= 100 - SUSTAIN_FRAMES
    assert all(m.x < 0 and m.y < 0 for m in moves)


@pytest.mark.parametrize("name,expected", [("u", (1, -1)), ("a", (1, 1))])
def test_ooo_and_ahh_move_where_the_mapping_says(name, expected):
    runner, sink, made = _runner()
    runner.start()
    made[0].push(vowel(PETERSON_BARNEY_MALE[name], 0.8))
    moves = _moves(sink)
    assert moves
    assert {(int(np.sign(m.x)), int(np.sign(m.y))) for m in moves} == {expected}


def test_running_speech_like_vowel_changes_never_move_the_pointer():
    """Vowel quality changing every 80 ms -- shorter than the 150 ms sustain -- steers nothing."""
    parts = []
    for k in range(12):
        parts.append(vowel(PETERSON_BARNEY_MALE["iau"[k % 3]], 0.08))
    runner, sink, made = _runner()
    runner.start()
    made[0].push(np.concatenate(parts))
    assert _moves(sink) == [] and _clicks(sink) == []


@pytest.mark.parametrize("audio", [
    silence(1.0),
    white_noise(1.0, level=0.01),
    _i(1.0, amp=0.0003),  # about -70 dBFS: a distant voice
], ids=["silence", "noise", "quiet-vowel"])
def test_silence_noise_and_a_quiet_voice_do_nothing(audio):
    runner, sink, made = _runner()
    runner.start()
    made[0].push(audio)
    assert sink.actions == []


def test_a_held_vowel_then_a_held_pitch_jump_clicks_exactly_once():
    runner, sink, made = _runner()
    runner.start()
    made[0].push(np.concatenate([_i(0.4, f0=120.0), _i(0.4, f0=300.0)]))
    assert len(_clicks(sink)) == 1


def test_a_pitch_jump_without_a_held_vowel_before_it_does_not_click():
    runner, sink, made = _runner()
    runner.start()
    made[0].push(np.concatenate([silence(0.3), _i(0.05, f0=120.0), _i(0.4, f0=300.0)]))
    assert _clicks(sink) == []


def test_nothing_is_steered_while_dictation_is_busy():
    busy = [True]
    runner, sink, made = _runner(busy=lambda: busy[0])
    runner.start()
    made[0].push(_i(1.0))
    assert sink.actions == []
    busy[0] = False
    made[0].push(_i(1.0))
    assert _moves(sink)


def test_a_failing_pointer_faults_the_runner_and_stops_acting():
    runner, sink, made = _runner()
    runner.start()
    sink.fail_with()
    made[0].push(_i(1.0))
    assert runner.fault.startswith("pointer output failed")
    sink.clear_failure()
    made[0].push(_i(1.0))
    assert _moves(sink) == []
    assert runner.start() == (True, "")  # an explicit resume recovers
    made[-1].push(_i(1.0))
    assert _moves(sink)


# --------------------------------------------------------------------------- #
# The click guards, frame by frame
# --------------------------------------------------------------------------- #
def _frame(pitch: float, direction: str | None = None, loud: float = 0.6):
    from yazses.vocaljoystick.formants import VocalFrame

    return VocalFrame(t_s=0.0, f1_hz=0.0, f2_hz=0.0, pitch_hz=pitch, voiced=pitch > 0.0,
                      rms=0.01, loudness=loud, direction=direction)


def _driver(**kw):
    from yazses.vocaljoystick.control import VocalJoystick
    from yazses.vocaljoystick.drive import SustainedVowelDriver

    return SustainedVowelDriver(VocalJoystick(), **kw)


def test_a_one_frame_octave_error_is_not_a_click():
    driver = _driver()
    out = [driver.feed(_frame(140.0)) for _ in range(30)]
    out += [driver.feed(_frame(280.0)), driver.feed(_frame(140.0))]  # one frame up, then back
    out += [driver.feed(_frame(140.0)) for _ in range(30)]
    assert all(o is None for o in out)


def test_clicks_are_spaced_by_the_refractory_period():
    from yazses.vocaljoystick.drive import CLICK_REFRACTORY_FRAMES

    driver = _driver()
    kinds = []
    for _ in range(4):  # four hold-then-jump gestures, back to back
        kinds += [driver.feed(_frame(140.0)) for _ in range(20)]
        kinds += [driver.feed(_frame(300.0)) for _ in range(8)]
    clicks = [i for i, k in enumerate(kinds) if k is not None and k.kind == "click"]
    assert len(clicks) >= 2
    assert all(b - a >= CLICK_REFRACTORY_FRAMES for a, b in zip(clicks, clicks[1:], strict=False))


def test_clicks_can_be_held_off_for_a_backend_without_a_left_button():
    driver = _driver(clicks=False)
    out = [driver.feed(_frame(140.0)) for _ in range(30)]
    out += [driver.feed(_frame(300.0)) for _ in range(10)]
    assert all(o is None or o.kind != "click" for o in out)


def test_resume_says_when_clicks_are_off(monkeypatch):
    """A backend with no left button is not hidden in the log: the resume reply names it."""
    import yazses.core.daemon as daemon_mod
    from yazses.pointer.base import PointerCapabilities

    FakeRecorder.instances.clear()
    monkeypatch.setattr(daemon_mod, "AudioRecorder", lambda **kw: FakeRecorder(kw["on_chunk"]))
    sink = FakePointerSink(PointerCapabilities(backend="fake-nobuttons", relative_motion=True))
    cfg = Config()
    cfg.vocaljoystick.enabled = True
    daemon = _daemon(cfg, sink)
    daemon._vocaljoystick = daemon._build_vocaljoystick(cfg)
    daemon._state.state = TrayState.IDLE
    try:
        reply = daemon._handle_handsfree(Request("handsfree", {"action": "resume"}))
        assert reply["ok"] is True
        (label,) = reply["scope"]  # type: ignore[misc]
        assert "clicks are off" in label and "fake-nobuttons" in label
    finally:
        daemon._vocaljoystick.stop()
