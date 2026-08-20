"""`yazses doctor` enrichment: version + daemon status, STT model availability,
config/hotkey summary, and an opt-in mic-level-vs-VAD check.

Each check is a small pure helper returning a ``(name, status, detail)`` tuple
(or a list of them), mirroring the existing prosody/dysfluency check style.
"""
from __future__ import annotations

import types
from pathlib import Path

from yazses.config import load_config
from yazses.system import doctor


def test_version_check_reports_installed_version():
    name, status, detail = doctor._version_check()
    assert "version" in name.lower()
    assert status == "OK"
    assert "yazses" in detail.lower()


def _fake_platform(*, running: bool, pid=4242, status_info=None, raise_ipc=False):
    def _factory(_socket):
        def _call(method, **_params):
            if raise_ipc:
                raise RuntimeError("IPC not ready")
            return status_info or {}
        return types.SimpleNamespace(call=_call)

    return types.SimpleNamespace(
        lifecycle=types.SimpleNamespace(
            is_running=lambda: running,
            read_pid=lambda: pid if running else None,
        ),
        ipc_client_factory=_factory,
        paths=types.SimpleNamespace(ipc_socket=Path("/tmp/yz.sock")),
    )


def test_daemon_check_warns_when_not_running():
    (name, status, detail), _info = doctor._daemon_check(_fake_platform(running=False))
    assert status == "WARN"
    assert "not running" in detail.lower()
    assert "yazses start" in detail.lower()


def test_daemon_check_reports_state_via_ipc():
    # The version has to be here for this to model a *healthy* daemon: an upgrade
    # leaves the old process running, and a daemon that reports no version is
    # necessarily older than the CLI asking (tests/test_doctor_stale_daemon.py).
    # Read rather than hardcoded, so a release bump does not turn this red.
    plat = _fake_platform(
        running=True, pid=1234,
        status_info={
            "state": "idle",
            "model": "small.en",
            "version": doctor._pkg_version("yazses"),
        },
    )
    (name, status, detail), _info = doctor._daemon_check(plat)
    assert status == "OK"
    assert "1234" in detail
    assert "idle" in detail
    assert "small.en" in detail
    # The payload comes back with the row so later checks can compare the daemon's
    # live values against the config file without a second IPC round trip. Dropping
    # it is how `doctor` came to print `[OK]` on a hotkey nobody was listening for
    # (tests/test_doctor_hotkey_drift.py).
    assert _info.get("state") == "idle"


def test_daemon_check_ok_when_ipc_unreachable():
    plat = _fake_platform(running=True, pid=99, raise_ipc=True)
    (name, status, detail), _info = doctor._daemon_check(plat)
    assert status == "OK"
    assert "99" in detail


def test_model_check_ok_when_cached(tmp_path):
    cache = tmp_path / "hub"
    (cache / "models--Systran--faster-whisper-base.en" / "snapshots").mkdir(parents=True)
    name, status, detail = doctor._model_check("base.en", cache)
    assert status == "OK"
    assert "base.en" in detail


def test_model_check_warns_when_absent(tmp_path):
    cache = tmp_path / "hub"
    cache.mkdir()
    name, status, detail = doctor._model_check("medium.en", cache)
    assert status == "WARN"
    assert "medium.en" in detail
    assert "download" in detail.lower() or "first" in detail.lower()


def test_model_check_ok_for_local_path(tmp_path):
    local = tmp_path / "my-model"
    local.mkdir()
    name, status, detail = doctor._model_check(str(local), tmp_path / "hub")
    assert status == "OK"


def test_model_check_does_not_confuse_similar_names(tmp_path):
    cache = tmp_path / "hub"
    (cache / "models--Systran--faster-whisper-small.en" / "snapshots").mkdir(parents=True)
    # base.en is NOT cached even though small.en is.
    _, status, _ = doctor._model_check("base.en", cache)
    assert status == "WARN"


def test_config_summary_shows_hotkey_and_file(tmp_path):
    cfg = load_config(None)
    cfg.hotkey.key = "right_alt"
    cfg.hotkey.hold_threshold_ms = 500
    checks = doctor._config_summary(cfg, tmp_path / "config.toml")
    blob = " ".join(f"{n} {s} {d}" for n, s, d in checks).lower()
    assert "right_alt" in blob
    assert "500" in blob
    assert "config" in blob


def test_mic_level_check_warns_when_noise_exceeds_threshold(monkeypatch):
    cfg = load_config(None)
    cfg.accessibility.vad_threshold = 0.01
    stats = doctor.LevelStats(  # type: ignore[attr-defined]
        duration_s=0.1, mean_abs=0.05, peak=0.1,
        recommended_threshold=0.07, is_silent=False,
    )
    monkeypatch.setattr(doctor, "_sample_mic", lambda cfg, seconds: stats)
    name, status, detail = doctor._mic_level_check(cfg, seconds=0.1)
    assert status == "WARN"
    assert "0.01" in detail


def test_mic_level_check_ok_when_quiet(monkeypatch):
    cfg = load_config(None)
    cfg.accessibility.vad_threshold = 0.02
    stats = doctor.LevelStats(  # type: ignore[attr-defined]
        duration_s=0.1, mean_abs=0.001, peak=0.005,
        recommended_threshold=0.0021, is_silent=True,
    )
    monkeypatch.setattr(doctor, "_sample_mic", lambda cfg, seconds: stats)
    name, status, detail = doctor._mic_level_check(cfg, seconds=0.1)
    assert status == "OK"


def test_mic_level_check_warns_when_sampling_fails(monkeypatch):
    cfg = load_config(None)

    def _boom(cfg, seconds):
        raise OSError("no input device")

    monkeypatch.setattr(doctor, "_sample_mic", _boom)
    _, status, detail = doctor._mic_level_check(cfg, seconds=0.1)
    assert status == "WARN"
    assert "could not sample" in detail.lower()


def test_config_summary_warns_when_file_absent_and_shows_primed_prompt(tmp_path):
    cfg = load_config(None)
    cfg.stt.initial_prompt = "kubernetes terraform helm"
    checks = doctor._config_summary(cfg, tmp_path / "missing.toml")
    by_name = {n: (s, d) for n, s, d in checks}
    assert by_name["Config file"][0] == "WARN"
    assert "absent" in by_name["Config file"][1].lower()
    # Assert the prompt itself reaches the row, not the label that introduces it --
    # the wording changed when the row learned to name every source it merges.
    assert "kubernetes terraform helm" in by_name["STT prompt"][1]


def test_mic_level_warns_when_the_gate_sits_under_a_quiet_room(monkeypatch):
    """The case the check exists for, and the one it could not report.

    Measured on a real machine: ambient 0.0010 against `vad_threshold` 0.0005.
    The gate sits below the room's noise floor, so ordinary silence passes it and
    reaches the model, which answers near-silence with a confident invented word.
    `yazses doctor --mic` printed:

        [OK] Mic level: ambient 0.0010 under vad_threshold 0.0005

    0.0010 is not under 0.0005. The warning was conditioned on
    `not stats.is_silent`, and `is_silent` is computed against a **fixed** floor
    (`miclevel._MIN_THRESHOLD`, 0.002) that has nothing to do with the user's
    threshold — so for any threshold below that floor the warning is suppressed
    across exactly the band where the gate is under the room, and the OK branch
    then asserts "under" for a value that is over.
    """
    from yazses.system.miclevel import _MIN_THRESHOLD

    cfg = load_config(None)
    cfg.accessibility.vad_threshold = 0.0005
    ambient = 0.0010
    assert ambient < _MIN_THRESHOLD, "fixture must sit in the suppressed band"

    stats = doctor.LevelStats(  # type: ignore[attr-defined]
        duration_s=0.1, mean_abs=ambient, peak=0.004,
        recommended_threshold=0.002, is_silent=True,
    )
    monkeypatch.setattr(doctor, "_sample_mic", lambda cfg, seconds: stats)
    name, status, detail = doctor._mic_level_check(cfg, seconds=0.1)
    assert status == "WARN", (
        f"the gate is below the room's noise floor and this reported {status}: {detail}"
    )
    assert "under" not in detail, f"a value that is over was described as under: {detail}"


def test_mic_level_ok_line_states_a_true_relation(monkeypatch):
    """The OK branch asserted "under" without ever checking it."""
    cfg = load_config(None)
    cfg.accessibility.vad_threshold = 0.02
    stats = doctor.LevelStats(  # type: ignore[attr-defined]
        duration_s=0.1, mean_abs=0.001, peak=0.005,
        recommended_threshold=0.0021, is_silent=True,
    )
    monkeypatch.setattr(doctor, "_sample_mic", lambda cfg, seconds: stats)
    _n, status, detail = doctor._mic_level_check(cfg, seconds=0.1)
    assert status == "OK"
    assert "0.0010" in detail and "0.02" in detail
    assert "under" in detail, "genuinely under: the word is correct here"


def test_a_dead_microphone_is_not_blamed_on_the_gate(monkeypatch):
    """Nothing captured at all is the Microphone check's business, not this one."""
    cfg = load_config(None)
    cfg.accessibility.vad_threshold = 0.0
    stats = doctor.LevelStats(  # type: ignore[attr-defined]
        duration_s=0.1, mean_abs=0.0, peak=0.0,
        recommended_threshold=0.002, is_silent=True,
    )
    monkeypatch.setattr(doctor, "_sample_mic", lambda cfg, seconds: stats)
    _n, status, _d = doctor._mic_level_check(cfg, seconds=0.1)
    assert status == "OK", "a silent capture must not be reported as room noise"


def test_doctor_names_the_microphone_behind_the_alias(monkeypatch):
    """`OS default: default` is the least useful true thing doctor can say.

    `doctor` is the surface the documentation points at first, and on a PipeWire
    desktop it reported the routing alias verbatim — the same gap `audio status`
    had. On the machine that prompted this, the alias pointed at an internal
    microphone array at 65% gain while a second source sat at 100%, and every
    dictation for an hour decoded to nothing.
    """
    monkeypatch.setattr(
        "yazses.audio.devices.current_default_input_name", lambda: "default"
    )
    monkeypatch.setattr(
        "yazses.audio.devices.default_source_behind_alias",
        lambda: ("Raptor Lake-P/U/H cAVS Digital Microphone", 0.65),
    )
    detail = next(
        d for n, _s, d in doctor._config_summary(load_config(None), Path("/nonexistent.toml"))
        if n == "Input device"
    )
    assert "Digital Microphone" in detail, detail
    assert "65%" in detail, f"the gain is half the diagnosis: {detail}"


def test_doctor_says_nothing_extra_when_the_default_is_a_real_device(monkeypatch):
    """No alias, nothing to resolve — the line must not grow a redundant arrow."""
    monkeypatch.setattr(
        "yazses.audio.devices.current_default_input_name", lambda: "USB PnP Audio Device"
    )
    monkeypatch.setattr(
        "yazses.audio.devices.default_source_behind_alias",
        lambda: ("something else entirely", 1.0),
    )
    detail = next(
        d for n, _s, d in doctor._config_summary(load_config(None), Path("/nonexistent.toml"))
        if n == "Input device"
    )
    assert "→" not in detail and "something else" not in detail, detail
