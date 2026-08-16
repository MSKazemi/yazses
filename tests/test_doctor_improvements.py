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
    name, status, detail = doctor._daemon_check(_fake_platform(running=False))
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
    name, status, detail = doctor._daemon_check(plat)
    assert status == "OK"
    assert "1234" in detail
    assert "idle" in detail
    assert "small.en" in detail


def test_daemon_check_ok_when_ipc_unreachable():
    plat = _fake_platform(running=True, pid=99, raise_ipc=True)
    name, status, detail = doctor._daemon_check(plat)
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
    assert "primed" in by_name["STT prompt"][1].lower()
