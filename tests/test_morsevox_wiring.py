"""Vocal Morse is reachable from the daemon (ADR-v2-105, WIRE-MORSEVOX-001, #164).

The owner's decision (2026-10-22): Morse mode is entered by the spoken command "morse mode"
or by a long steady hum, left by a long silence; while it is on, decoded characters are typed
through the normal injector and speech-to-text is not run; the status surface shows it.

Claims pinned here, all with fakes (no microphone, no model, no injector, no notification):

* **A default install is unchanged.** `[morsevox]` ships off: the daemon imports nothing from
  `yazses.morsevox`, opens no stream, `status` carries ``morse: None``, "morse mode" is
  dictation, and the `handsfree` IPC replies exactly as before.
* **Enabled, it is reachable end to end.** Building opens no microphone; the daemon's start
  opens the level stream; a hum or the spoken command enters; the decoded letters reach the
  daemon's injector; the STT engine is never asked.
* **It yields.** A hold-to-talk recording ends Morse mode; `handsfree pause` closes the stream
  and `resume` reopens it; shutdown closes it; the device monitor never re-inits PortAudio
  under it, and closes and reopens it for a re-scan instead of going blind.
* **It is visible.** `status` reports the mode (never the text), the overlay draws its rings,
  and entering and leaving are announced.
"""
from __future__ import annotations

import ast
import inspect
import textwrap

import numpy as np
import pytest

from tests.test_dormant_features_stay_unimported import started, tripwire  # noqa: F401
from tests.test_morsevox_mode import LOUD, QUIET, levels, morse_runs
from yazses.config import Config
from yazses.ipc.protocol import Request
from yazses.platform import get_platform
from yazses.platform.base import TrayState
from yazses.system.features import feature_status, unwired_slugs


class FakeRecorder:
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


class FakeInjector:
    name = "fake"

    def __init__(self) -> None:
        self.typed: list[str] = []

    def inject(self, text: str) -> None:
        self.typed.append(text)

    def inject_backspaces(self, count: int) -> None:  # pragma: no cover - unused here
        pass


class NoSttEngine:
    """Any call fails the test: Morse mode must never reach speech-to-text."""

    name = "no-stt"

    def __getattr__(self, item):
        raise AssertionError(f"Morse mode reached the STT engine ({item})")


def _cfg(*, enabled: bool = True, entry_hum_s: float = 1.5) -> Config:
    cfg = Config()
    cfg.morsevox.enabled = enabled
    cfg.morsevox.entry_hum_s = entry_hum_s
    cfg.accessibility.vad_threshold = 0.02  # the level units of tests/test_morsevox_mode.py
    return cfg


def _daemon(cfg: Config):
    from yazses.core.daemon import Daemon

    return Daemon(config=cfg, platform=get_platform())


@pytest.fixture
def morse_daemon(monkeypatch):
    """An enabled daemon with fakes behind the recorder, injector, engine and notifier."""
    import yazses.core.daemon as daemon_mod
    import yazses.system.notify as notify_mod

    FakeRecorder.instances.clear()
    monkeypatch.setattr(daemon_mod, "AudioRecorder", lambda **kw: FakeRecorder(kw["on_chunk"]))
    told: list[tuple[str, str]] = []
    monkeypatch.setattr(notify_mod, "notify", lambda title, body, **kw: told.append((title, body)))

    def build(cfg: Config | None = None):
        daemon = _daemon(cfg or _cfg())
        daemon._injector = FakeInjector()
        daemon._engine = NoSttEngine()
        daemon._morsevox = daemon._build_morsevox(daemon._config)
        daemon._state.state = TrayState.IDLE
        made.append(daemon)
        return daemon

    made: list = []
    build.told = told  # type: ignore[attr-defined]
    yield build
    for daemon in made:
        if daemon._morsevox is not None:
            daemon._morsevox.stop()


def _drive(daemon, samples) -> None:
    runner = daemon._morsevox
    runner._use_thread = False  # drive the per-sample path inline, with our own timestamps
    for t, lv in samples:
        runner.process(t, lv)


# --------------------------------------------------------------------------- #
# Registry honesty
# --------------------------------------------------------------------------- #
def test_morsevox_is_no_longer_advertised_as_unwired():
    assert "morsevox" not in unwired_slugs()
    feature = next(f for f in feature_status(Config()) if f.slug == "morsevox")
    assert feature.wired is True


def test_the_registry_says_how_it_starts_and_stops():
    from yazses.system.features import _registry

    definition = next(d for d in _registry() if d.slug == "morsevox")
    assert "'morse mode'" in definition.why
    assert "long steady tone" in definition.why
    assert "silence" in definition.why
    assert "speech-to-text is not run" in definition.why


@pytest.mark.parametrize("hum,warns", [(1.5, True), (-1.0, True), (float("nan"), True),
                                       ("soon", True), (0, False), (0.0, False)])
def test_enabling_it_says_the_microphone_stays_open_when_the_hum_entry_listens(hum, warns):
    from yazses.system.features import enable_caveat

    cfg = Config()
    cfg.morsevox.entry_hum_s = hum  # type: ignore[assignment]
    caveat = enable_caveat("morsevox", cfg)
    assert (caveat is not None) is warns
    if warns:
        assert caveat is not None and "microphone stays open" in caveat
        assert "entry_hum_s = 0" in caveat


def test_the_new_keys_ship_with_the_owner_defaults_and_the_feature_off():
    section = Config().morsevox
    assert section.enabled is False
    assert (section.entry_hum_s, section.exit_silence_s) == (1.5, 3.0)


# --------------------------------------------------------------------------- #
# A default install is unchanged
# --------------------------------------------------------------------------- #
def test_a_default_daemon_never_imports_vocal_morse(tripwire, started):  # noqa: F811
    daemon = started(Config())
    assert "morsevox" not in tripwire.packages()
    assert daemon._morsevox is None


def test_an_enabled_daemon_imports_and_builds_it(tripwire, started):  # noqa: F811
    """The positive control for the test above: the tripwire does see the import, and the
    real `_build_pipeline` builds the runner. Building constructs no recorder at all (the
    factory is only called by `_start_morsevox`), so no stream can be open."""
    daemon = started(_cfg())
    assert "morsevox" in tripwire.packages()
    assert daemon._morsevox is not None
    assert daemon._morsevox.mic_open is False


def test_a_default_daemon_types_morse_mode_as_dictation_and_reports_nothing():
    daemon = _daemon(Config())
    event: dict = {}
    assert daemon._try_morse_mode("morse mode", event) is False
    assert event == {}
    assert daemon._handle_status(None)["morse"] is None


def test_the_default_handsfree_replies_are_unchanged():
    daemon = _daemon(Config())
    assert daemon._handle_handsfree(Request("handsfree", {"action": "pause"})) == {
        "ok": False,
        "reason": "nothing hands-free is running, and the global stop is off "
        "(`[handsfree_safety] enabled = false`)",
    }
    assert daemon._handle_handsfree(Request("handsfree", {"action": "resume"})) == {
        "ok": False, "reason": "nothing hands-free is running",
    }


def test_an_unusable_threshold_leaves_it_off_with_a_reason(caplog):
    cfg = _cfg()
    cfg.accessibility.vad_threshold = 0.0
    with caplog.at_level("WARNING", logger="yazses.core.daemon"):
        assert _daemon(cfg)._build_morsevox(cfg) is None
    assert any("threshold" in r.getMessage() for r in caplog.records)


# --------------------------------------------------------------------------- #
# Reachable end to end
# --------------------------------------------------------------------------- #
def test_the_daemon_start_opens_the_level_stream(morse_daemon):
    daemon = morse_daemon()
    assert FakeRecorder.instances == []
    daemon._start_morsevox()
    (rec,) = FakeRecorder.instances
    assert rec.open


def test_without_the_hum_entry_the_start_opens_nothing(morse_daemon):
    daemon = morse_daemon(_cfg(entry_hum_s=0))
    daemon._start_morsevox()
    assert FakeRecorder.instances == []


def test_a_long_hum_enters_and_the_letters_reach_the_daemons_injector(morse_daemon):
    daemon = morse_daemon()
    daemon._start_morsevox()
    samples, _ = levels([(500, QUIET), (2000, LOUD)] + morse_runs("sos") + [(3500, QUIET)])
    _drive(daemon, samples)
    assert "".join(daemon._injector.typed) == "sos "
    # Typed with the daemon idle: no burst was recorded, transcribed or counted.
    assert daemon._state.state is TrayState.IDLE
    titles = [t for t, _ in morse_daemon.told]
    assert titles == ["YazSes — Vocal Morse"] * 2  # on, then off
    assert "Morse mode on" in morse_daemon.told[0][1]
    assert "silence" in morse_daemon.told[1][1]


@pytest.mark.parametrize("said", ["morse mode", "Morse mode.", "MORSE-MODE"])
def test_the_spoken_command_enters_and_types_nothing(morse_daemon, said):
    daemon = morse_daemon(_cfg(entry_hum_s=0))
    event: dict = {}
    assert daemon._try_morse_mode(said, event) is True
    assert event["intent_type"] == "morse_mode" and event["command_mode"] is True
    assert daemon._morsevox.active
    (rec,) = FakeRecorder.instances
    assert rec.open
    assert daemon._injector.typed == []


def test_a_sentence_containing_the_words_is_dictation(morse_daemon):
    daemon = morse_daemon()
    event: dict = {}
    assert daemon._try_morse_mode("I will switch to morse mode later", event) is False
    assert event == {} and not daemon._morsevox.active


def test_the_command_heard_in_the_transcribing_state_does_not_end_the_mode_at_once(morse_daemon):
    """The phrase is handled while the daemon is TRANSCRIBING. That must count as quiet."""
    daemon = morse_daemon(_cfg(entry_hum_s=0))
    daemon._state.state = TrayState.TRANSCRIBING
    clock_ms = daemon._morsevox._now_ms()
    assert daemon._try_morse_mode("morse mode", {}) is True
    _drive(daemon, [(clock_ms, QUIET), (clock_ms + 20, QUIET)])
    assert daemon._morsevox.active


def test_a_command_that_cannot_start_is_still_consumed_and_says_why(morse_daemon):
    daemon = morse_daemon()
    daemon._morsevox.toggle("pause", [], [])
    event: dict = {}
    assert daemon._try_morse_mode("morse mode", event) is True  # never typed
    assert not daemon._morsevox.active
    assert any("did not start" in body for _, body in morse_daemon.told)


def test_the_morse_check_sits_after_the_stop_word_and_before_anything_types():
    from yazses.core.daemon import Daemon

    tree = ast.parse(textwrap.dedent(inspect.getsource(Daemon._on_hold_end)))
    first: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            first.setdefault(node.func.attr, node.lineno)
            first[node.func.attr] = min(first[node.func.attr], node.lineno)
    assert first["_try_voice_stop"] < first["_try_morse_mode"]
    for later in ("_try_deixis", "_try_window_action", "_cmdsafety_gate", "_stage_or_commit",
                  "inject", "classify"):
        if later in first:
            assert first["_try_morse_mode"] < first[later], later
    guard = next(
        n for n in ast.walk(tree) if isinstance(n, ast.If)
        and any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                and c.func.attr == "_try_morse_mode" for c in ast.walk(n.test))
    )
    assert any(isinstance(n, ast.Return) for n in guard.body), "the command must end the burst"


# --------------------------------------------------------------------------- #
# It yields
# --------------------------------------------------------------------------- #
def test_a_hold_to_talk_recording_ends_morse_mode(morse_daemon):
    daemon = morse_daemon()
    daemon._start_morsevox()
    assert daemon._try_morse_mode("morse mode", {}) is True
    t = daemon._morsevox._now_ms()
    _drive(daemon, [(t, QUIET)])
    daemon._state.state = TrayState.RECORDING
    _drive(daemon, [(t + 20, LOUD)])
    assert not daemon._morsevox.active
    assert "dictation started" in morse_daemon.told[-1][1]


def test_handsfree_pause_closes_the_stream_and_resume_reopens_it(morse_daemon):
    daemon = morse_daemon()
    daemon._start_morsevox()
    (rec,) = FakeRecorder.instances
    reply = daemon._handle_handsfree(Request("handsfree", {"action": "pause"}))
    assert reply == {"ok": True, "scope": ["Vocal Morse"]}
    assert not rec.open
    reply = daemon._handle_handsfree(Request("handsfree", {"action": "resume"}))
    assert reply == {"ok": True, "scope": ["Vocal Morse (listening for the entry hum)"]}
    assert FakeRecorder.instances[-1].open


def test_the_spoken_stop_phrase_ends_morse_mode(morse_daemon):
    daemon = morse_daemon()
    daemon._config.handsfree_safety.stop_phrase = "pause hands free"
    daemon._start_morsevox()
    daemon._try_morse_mode("morse mode", {})
    assert daemon._try_voice_stop("pause hands free", {}) is True
    assert not daemon._morsevox.active
    assert not FakeRecorder.instances[0].open


def test_the_device_monitor_waits_while_the_stream_is_open(morse_daemon):
    daemon = morse_daemon()
    assert daemon._audio_idle() is True
    daemon._start_morsevox()
    assert daemon._audio_idle() is False
    daemon._handle_handsfree(Request("handsfree", {"action": "pause"}))
    assert daemon._audio_idle() is True


def _monitor_like_the_daemon(daemon, poll, clock):
    """A `DeviceMonitor` wired to the daemon's own idle, recording and owner callbacks."""
    from yazses.audio.device_monitor import DeviceMonitor

    fired: list[tuple] = []
    monitor = DeviceMonitor(
        poll_fn=poll,
        is_idle=daemon._audio_idle,
        on_change=lambda prev, cur: fired.append((prev, cur)),
        level_streams=daemon._level_stream_owners,
        recording=daemon._recording_in_flight,
        clock=lambda: clock[0],
    )
    return monitor, fired


def test_the_device_monitor_re_scans_while_the_hum_entry_listens(morse_daemon):
    """The reported bug: with `[morsevox]` on, the watcher never re-scanned all session."""
    from yazses.audio.device_monitor import LEVEL_STREAM_RESCAN_S

    daemon = morse_daemon()
    daemon._start_morsevox()
    assert daemon._level_stream_owners() == [daemon._morsevox]
    device = ["MicA"]
    reinit_under_open_stream: list[bool] = []

    def poll():
        reinit_under_open_stream.append(any(r.open for r in FakeRecorder.instances))
        return device[0]

    clock = [0.0]
    monitor, fired = _monitor_like_the_daemon(daemon, poll, clock)
    clock[0] = LEVEL_STREAM_RESCAN_S
    monitor.poll_once()  # the baseline, through a close / re-init / reopen
    device[0] = "Bluetooth headset"
    clock[0] = 2 * LEVEL_STREAM_RESCAN_S
    assert monitor.poll_once() is True
    assert fired == [("MicA", "Bluetooth headset")]
    assert reinit_under_open_stream == [False, False]
    assert len(FakeRecorder.instances) == 3  # the first stream, then one per re-scan
    assert FakeRecorder.instances[-1].open and daemon._morsevox.mic_open


def test_the_device_monitor_touches_nothing_while_dictation_records(morse_daemon):
    from yazses.audio.device_monitor import LEVEL_STREAM_RESCAN_S

    daemon = morse_daemon()
    daemon._start_morsevox()
    polled: list[int] = []
    clock = [10 * LEVEL_STREAM_RESCAN_S]
    monitor, _ = _monitor_like_the_daemon(daemon, lambda: polled.append(1) or "MicA", clock)
    daemon._state.state = TrayState.RECORDING
    assert monitor.poll_once() is False
    assert polled == [] and len(FakeRecorder.instances) == 1
    assert FakeRecorder.instances[0].open, "a hold-to-talk never loses the hum listener"


def test_the_daemon_hands_the_monitor_its_level_streams():
    """`_build_pipeline` must pass the owners, the recording check and the peek reader."""
    from yazses.core.daemon import Daemon

    tree = ast.parse(textwrap.dedent(inspect.getsource(Daemon._build_pipeline)))
    call = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        and n.func.id == "DeviceMonitor"
    )
    keywords = {kw.arg: ast.unparse(kw.value) for kw in call.keywords}
    assert keywords["is_idle"] == "self._audio_idle"
    assert keywords["level_streams"] == "self._level_stream_owners"
    assert keywords["recording"] == "self._recording_in_flight"
    assert keywords["peek_fn"] == "effective_default_input_name"


def test_shutdown_closes_the_stream(morse_daemon):
    daemon = morse_daemon()
    daemon._start_morsevox()
    (rec,) = FakeRecorder.instances
    daemon._morsevox.stop()
    assert not rec.open


def test_shutdown_stops_it():
    """`_shutdown` itself names the runner (read off its source, as the semantics test does)."""
    from yazses.core.daemon import Daemon

    assert "self._morsevox.stop()" in inspect.getsource(Daemon._shutdown)


# --------------------------------------------------------------------------- #
# It is visible
# --------------------------------------------------------------------------- #
def test_status_reports_the_mode_and_never_the_text(morse_daemon):
    daemon = morse_daemon()
    daemon._start_morsevox()
    samples, _ = levels([(2000, LOUD)] + morse_runs("hi") + [(1000, QUIET)])
    _drive(daemon, samples)
    assert "".join(daemon._injector.typed).startswith("hi")
    block = daemon._handle_status(None)["morse"]
    assert block["active"] is True and block["entered_by"] == "hum"
    assert block["listening"] is True
    assert "hi" not in repr({k: v for k, v in block.items() if k != "typed_chars"})


def test_the_overlay_draws_rings_while_morse_mode_is_on(morse_daemon):
    from yazses.config import OverlayConfig
    from yazses.overlay.animation import SonarModel
    from yazses.overlay.app import compute_frame
    from yazses.overlay.envelope import EnvelopeFollower
    from yazses.overlay.poller import next_interval, parse_status

    daemon = morse_daemon()
    daemon._start_morsevox()
    daemon._try_morse_mode("morse mode", {})
    t = daemon._morsevox._now_ms()
    _drive(daemon, [(t, QUIET), (t + 20, LOUD), (t + 40, LOUD)])
    info = daemon._handle_status(None)
    assert info["state"] == "idle"  # the daemon is not recording...
    snap = parse_status(info)
    assert snap.morse_active is True  # ...but the overlay knows Morse mode is on
    assert snap.audio_level == pytest.approx(LOUD, rel=0.01)
    assert next_interval(snap.state, morse_active=snap.morse_active) < next_interval("idle")
    frame = compute_frame(snap, OverlayConfig(), EnvelopeFollower(), SonarModel(),
                          now=0.0, cursor=(500, 400), screen=(0, 0, 1920, 1080))
    assert frame.visible is True
    # The control: the same reply without the Morse block draws nothing.
    idle = parse_status({**info, "morse": None})
    hidden = compute_frame(idle, OverlayConfig(), EnvelopeFollower(), SonarModel(),
                           now=0.0, cursor=(500, 400), screen=(0, 0, 1920, 1080))
    assert hidden.visible is False


def test_the_overlay_ignores_a_missing_or_malformed_block():
    from yazses.overlay.poller import parse_status

    assert parse_status({"state": "idle"}).morse_active is False
    assert parse_status({"state": "idle", "morse": None}).morse_active is False
    assert parse_status({"state": "idle", "morse": {"active": "yes"}}).morse_active is False


def test_leaving_the_mode_calms_the_overlay(morse_daemon):
    daemon = morse_daemon()
    daemon._start_morsevox()
    daemon._try_morse_mode("morse mode", {})
    t = daemon._morsevox._now_ms()
    _drive(daemon, [(t, QUIET), (t + 20, LOUD)])
    assert daemon._state.audio_level > 0
    daemon._morsevox.stop()
    assert daemon._state.audio_level == 0.0


def test_the_cli_status_line_names_the_mode():
    from yazses.morsevox.mode import describe_status

    line = describe_status({"active": True, "entered_by": "hum", "typed_chars": 3})
    assert line.startswith("ON") and "3" not in line


def test_the_status_block_is_a_machine_fact_in_the_bug_report_ledger():
    from tests.test_report_redacts_the_daemon_block import _MACHINE_FACTS

    assert "morse" in _MACHINE_FACTS


def test_the_runner_holds_no_daemon_lock_while_asking_busy(morse_daemon):
    """`status` holds the daemon lock and then asks the runner; the runner's busy check must
    therefore read the state without that lock, or the two would deadlock."""
    daemon = morse_daemon()
    acquired: list[bool] = []
    real = daemon._lock

    class SpyLock:
        def __enter__(self):
            acquired.append(True)
            return real.__enter__()

        def __exit__(self, *exc):
            return real.__exit__(*exc)

    daemon._lock = SpyLock()
    try:
        assert daemon._morsevox._safe_busy() is False
    finally:
        daemon._lock = real
    assert acquired == []


def test_build_uses_a_level_only_stream_without_a_recording_cap(monkeypatch):
    import yazses.core.daemon as daemon_mod

    seen: list[dict] = []

    def capture(**kw):
        seen.append(kw)
        return FakeRecorder(kw["on_chunk"])

    monkeypatch.setattr(daemon_mod, "AudioRecorder", capture)
    daemon = _daemon(_cfg())
    daemon._morsevox = daemon._build_morsevox(daemon._config)
    try:
        daemon._start_morsevox()
        (kw,) = seen
        assert kw["accumulate"] is False and kw["max_seconds"] == 0
    finally:
        daemon._morsevox.stop()
