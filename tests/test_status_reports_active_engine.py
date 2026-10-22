"""`yazses status` names the engine that decodes, not the one the config asked for (#644).

`stt/factory.py` falls back to faster-whisper when Parakeet or Moonshine is missing or
fails to load, and logs it. But `yazses status` printed `model: <[stt] model>`: with
`engine = "parakeet"` and a Parakeet that failed at load, it read
`nemo-parakeet-tdt-0.6b-v2` while `base.en` decoded every word. The daemon's status reply
had no engine field at all, so no surface could tell the two apart.

Now the built engine describes itself (`engine_name`, `model_name`), the factory stamps a
fallback with its cause, and the status reply carries `engine`, `engine_model` and
`engine_fallback`. `model` keeps its meaning (`[stt] model` as configured) because other
code reads it.
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

pytest.importorskip("faster_whisper", reason="the decoder stack has no FreeBSD build")

from yazses.cli import app
from yazses.config import Config, SttConfig
from yazses.core.daemon import Daemon
from yazses.platform import get_platform
from yazses.settingsui.restart import describe_status
from yazses.stt import factory
from yazses.stt.factory import build_engine, describe_active_engine, render_engine_status_lines


@pytest.fixture
def fake_whisper(monkeypatch):
    """FasterWhisperEngine constructible without a model (same fake as test_stt_factory)."""

    class _FakeModel:
        def __init__(self, model_name, device="cpu", compute_type="int8", **kwargs) -> None:
            pass

    monkeypatch.setattr("yazses.stt.faster_whisper.WhisperModel", _FakeModel)


@pytest.fixture
def parakeet_fails_to_load(monkeypatch):
    """onnx-asr is importable, and loading the model raises with a path in the message."""

    class _Exploding:
        def __init__(self, _config) -> None:
            raise RuntimeError(r"cannot open C:\Users\ada\models\parakeet.onnx")

    monkeypatch.setattr("yazses.stt.parakeet.ParakeetEngine", _Exploding)


# ---- the factory records what it built -------------------------------------------------


def test_the_default_engine_reports_itself_with_no_fallback(fake_whisper):
    info = describe_active_engine(build_engine(SttConfig()))
    assert info == {"engine": "faster-whisper", "model": "base.en",
                    "fallback_from": "", "fallback_reason": ""}


def test_a_missing_parakeet_package_is_named_as_the_fallback_cause(fake_whisper, monkeypatch):
    monkeypatch.setitem(sys.modules, "onnx_asr", None)
    info = describe_active_engine(build_engine(SttConfig(engine="parakeet")))
    assert info["engine"] == "faster-whisper"
    assert info["fallback_from"] == "parakeet"
    assert "onnx_asr is not installed" in info["fallback_reason"]
    assert "yazses features enable stt-parakeet" in info["fallback_reason"]


def test_a_parakeet_that_fails_to_load_is_named_as_the_fallback_cause(
    fake_whisper, parakeet_fails_to_load
):
    """The case `doctor` cannot see: the package is installed, the load fails."""
    engine = build_engine(SttConfig(engine="parakeet", model="nemo-parakeet-tdt-0.6b-v2"))
    info = describe_active_engine(engine)
    assert info["engine"] == "faster-whisper"
    assert info["model"] == "base.en", "the fallback must report the checkpoint it loaded"
    assert info["fallback_from"] == "parakeet"
    assert info["fallback_reason"].startswith("it failed to load (RuntimeError")


def test_a_load_error_reason_never_carries_the_exception_message(
    fake_whisper, parakeet_fails_to_load
):
    """Status output is pasted into public issues; the message held a home directory."""
    reason = describe_active_engine(build_engine(SttConfig(engine="parakeet")))["fallback_reason"]
    assert "ada" not in reason and "Users" not in reason and ".onnx" not in reason


def test_an_unknown_engine_name_is_a_reported_fallback(fake_whisper):
    info = describe_active_engine(build_engine(SttConfig(engine="whisperx")))
    assert info["engine"] == "faster-whisper"
    assert info["fallback_from"] == "whisperx"
    assert "not an engine YazSes knows" in info["fallback_reason"]


def test_the_wrapper_engines_forward_the_description(fake_whisper, monkeypatch):
    monkeypatch.setitem(sys.modules, "onnx_asr", None)
    inner = build_engine(SttConfig(engine="parakeet"))
    wrapped = factory._HanScriptEngine(inner, lambda s: s)
    assert describe_active_engine(wrapped) == describe_active_engine(inner)


@pytest.mark.parametrize("engine", [None, object(), MagicMock(), "whisper"])
def test_an_engine_that_does_not_describe_itself_is_unknown(engine):
    """Never invent an answer from config: that is the bug."""
    assert describe_active_engine(engine) is None


def test_a_fallback_survives_an_engine_that_refuses_attributes():
    """`_mark_fallback` must never raise: it runs on the path that keeps dictation up."""
    assert factory._mark_fallback("whisper", "parakeet", "x") == "whisper"


# ---- the daemon's status reply ---------------------------------------------------------


def _daemon() -> Daemon:
    return Daemon(config=Config(), platform=get_platform())


def test_the_status_reply_carries_the_engine_that_came_up(fake_whisper, parakeet_fails_to_load):
    d = _daemon()
    d._config.stt.engine = "parakeet"
    d._config.stt.model = "nemo-parakeet-tdt-0.6b-v2"
    d._engine = build_engine(d._config.stt)
    status = d._handle_status(None)
    assert status["model"] == "nemo-parakeet-tdt-0.6b-v2", "`model` keeps its meaning"
    assert status["engine"] == "faster-whisper"
    assert status["engine_model"] == "base.en"
    assert status["engine_fallback"]["from"] == "parakeet"
    assert "failed to load" in status["engine_fallback"]["reason"]


def test_the_status_reply_says_unknown_before_the_engine_exists():
    status = _daemon()._handle_status(None)
    assert (status["engine"], status["engine_model"], status["engine_fallback"]) == (None, None, None)


def test_no_fallback_is_reported_as_none(fake_whisper):
    d = _daemon()
    d._engine = build_engine(d._config.stt)
    status = d._handle_status(None)
    assert status["engine"] == "faster-whisper" and status["engine_fallback"] is None


# ---- what the user reads ---------------------------------------------------------------


def test_an_older_daemon_gets_the_old_line_unchanged():
    assert render_engine_status_lines({"model": "base.en"}) == ["  model:    base.en"]


def test_the_model_line_names_the_engine_actually_decoding():
    lines = render_engine_status_lines(
        {"model": "base.en", "engine": "faster-whisper", "engine_model": "base.en"}
    )
    assert lines == ["  model:    base.en (faster-whisper)"]


def test_a_fallback_gets_its_own_line_with_the_reason():
    lines = render_engine_status_lines({
        "model": "nemo-parakeet-tdt-0.6b-v2",
        "engine": "faster-whisper",
        "engine_model": "base.en",
        "engine_fallback": {"from": "parakeet", "reason": "it failed to load (RuntimeError)"},
    })
    assert lines[0] == "  model:    base.en (faster-whisper)"
    assert lines[1].startswith("  FALLBACK: [stt] engine = parakeet is not running, because it failed")
    assert "faster-whisper decodes instead" in lines[1]


def test_yazses_status_prints_the_fallback(monkeypatch):
    from yazses import cli

    reply = {
        "state": "idle", "hotkey": "right_ctrl", "model": "nemo-parakeet-tdt-0.6b-v2",
        "injection_backend": "SendInputInjector", "uptime_s": 5.0, "ready": True,
        "engine": "faster-whisper", "engine_model": "base.en",
        "engine_fallback": {"from": "parakeet", "reason": "it failed to load (RuntimeError)"},
    }

    class _Client:
        def is_reachable(self):
            return True

        def call(self, _method, **_kw):
            return reply

    class _Platform:
        name = "linux"

        class lifecycle:  # noqa: N801 - a stand-in namespace
            @staticmethod
            def read_pid():
                return 1234

            @staticmethod
            def is_running():
                return True

        class paths:  # noqa: N801
            ipc_socket = "/tmp/nope.sock"
            data_dir = "/tmp"
            config_file = "/tmp/config.toml"

        @staticmethod
        def ipc_client_factory(_s):
            return _Client()

    monkeypatch.setattr(cli, "get_platform", lambda: _Platform())
    out = CliRunner().invoke(app, ["status"]).output
    assert "model:    base.en (faster-whisper)" in out
    assert "nemo-parakeet" not in out.split("FALLBACK")[0], "the configured model is not what decodes"
    assert "FALLBACK: [stt] engine = parakeet is not running" in out


def test_the_settings_window_names_the_checkpoint_that_decodes():
    status = {"state": "idle", "model": "nemo-parakeet-tdt-0.6b-v2", "engine_model": "base.en"}
    assert describe_status(status) == "Running (state idle, model base.en)."


# ---- a status reply never fails, and survives an idle unload ----------------------------


class _Refuses:
    """An engine double whose attribute lookups raise something other than AttributeError."""

    def __getattr__(self, name):
        raise AssertionError(f"the engine was asked for {name}")


def test_an_engine_whose_lookups_raise_is_unknown_not_a_crash():
    assert describe_active_engine(_Refuses()) is None


def test_the_status_reply_survives_an_engine_whose_lookups_raise():
    d = _daemon()
    d._engine = _Refuses()
    status = d._handle_status(None)
    assert (status["engine"], status["engine_model"], status["engine_fallback"]) == (None, None, None)


class _Unloadable:
    """Describes itself while loaded; raises AttributeError once the model is released,
    as `stt/resident.py`'s IdleUnloadEngine does under `[stt] idle_unload_s`."""

    def __init__(self) -> None:
        self.loaded = True

    def __getattr__(self, name):
        if not self.__dict__.get("loaded"):
            raise AttributeError(name)
        return {"engine_name": "faster-whisper", "model_name": "base.en",
                "fallback_from": "parakeet", "fallback_reason": "it failed to load"}[name]


def test_a_fallback_is_still_reported_after_the_model_is_unloaded():
    d = _daemon()
    d._engine = _Unloadable()
    d._remember_engine_info()          # what _build_pipeline does once the engine exists
    d._engine.loaded = False           # idle unload released the model
    status = d._handle_status(None)
    assert status["engine"] == "faster-whisper"
    assert status["engine_fallback"] == {"from": "parakeet", "reason": "it failed to load"}


def test_a_remembered_description_never_outlives_its_engine():
    d = _daemon()
    d._engine = _Unloadable()
    d._remember_engine_info()
    d._engine = _Refuses()             # a different engine object, which says nothing
    assert d._handle_status(None)["engine"] is None
