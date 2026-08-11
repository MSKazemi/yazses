"""The pluggable STT engine factory (`[stt] engine`, stt/factory.py).

Guard-and-fallback contract: whatever the config says, dictation must come up —
on faster-whisper if the requested engine can't load — and every fallback is
logged honestly (never a silent engine switch).
"""
from __future__ import annotations

import logging
import sys

import pytest

from yazses.config import SttConfig
from yazses.stt.base import SttEngine
from yazses.stt.factory import build_engine
from yazses.stt.faster_whisper import FasterWhisperEngine


@pytest.fixture
def fake_whisper(monkeypatch):
    """Make FasterWhisperEngine constructible without loading a real model."""
    loaded: list[tuple] = []

    class _FakeModel:
        # **kwargs so the fake accepts `local_files_only`, which the real loader
        # passes on its first (cache-only) attempt; without it these fakes would
        # silently exercise the download fallback instead of the real path.
        def __init__(self, model_name, device="cpu", compute_type="int8", **kwargs) -> None:
            loaded.append((model_name, device, compute_type))

        def transcribe(self, audio, **kwargs):  # pragma: no cover - not exercised
            return [], None

    monkeypatch.setattr("yazses.stt.faster_whisper.WhisperModel", _FakeModel)
    return loaded


@pytest.fixture
def no_onnx_asr(monkeypatch):
    """Simulate the optional onnx-asr dependency being absent."""
    monkeypatch.setitem(sys.modules, "onnx_asr", None)  # import raises ModuleNotFoundError


def test_default_engine_is_faster_whisper(fake_whisper):
    engine = build_engine(SttConfig())
    assert isinstance(engine, FasterWhisperEngine)
    assert fake_whisper == [("base.en", "cpu", "int8")]


def test_engines_satisfy_the_protocol(fake_whisper):
    engine = build_engine(SttConfig())
    assert isinstance(engine, SttEngine)  # runtime_checkable: all methods present
    assert callable(engine.decode_window)


def test_parakeet_without_onnx_asr_falls_back_with_honest_warning(
    fake_whisper, no_onnx_asr, caplog
):
    with caplog.at_level(logging.WARNING, logger="yazses.stt.factory"):
        engine = build_engine(SttConfig(engine="parakeet"))
    assert isinstance(engine, FasterWhisperEngine)
    # The warning must name the one command that fixes it.
    assert any("yazses features enable stt-parakeet" in r.message for r in caplog.records)


def test_parakeet_fallback_never_hands_whisper_a_parakeet_model(
    fake_whisper, no_onnx_asr, caplog
):
    """`[stt] model` naming a Parakeet checkpoint must not crash the fallback."""
    with caplog.at_level(logging.WARNING, logger="yazses.stt.factory"):
        engine = build_engine(
            SttConfig(engine="parakeet", model="nemo-parakeet-tdt-0.6b-v2")
        )
    assert isinstance(engine, FasterWhisperEngine)
    assert fake_whisper[0][0] == "base.en"


def test_unknown_engine_falls_back_with_warning(fake_whisper, caplog):
    with caplog.at_level(logging.WARNING, logger="yazses.stt.factory"):
        engine = build_engine(SttConfig(engine="whisper-x"))
    assert isinstance(engine, FasterWhisperEngine)
    assert any("Unknown [stt] engine" in r.message for r in caplog.records)


def test_engine_name_is_normalized(fake_whisper, caplog):
    """Case/whitespace in the TOML value must not trigger the unknown-engine path."""
    with caplog.at_level(logging.WARNING, logger="yazses.stt.factory"):
        engine = build_engine(SttConfig(engine="  Faster-Whisper "))
    assert isinstance(engine, FasterWhisperEngine)
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_faster_whisper_has_the_streaming_seam():
    """StreamingEngine drives backends only through decode_window."""
    eng = FasterWhisperEngine.__new__(FasterWhisperEngine)

    class _Seg:
        text = " hello "

    eng._model = type("M", (), {"transcribe": lambda self, audio, **kw: ([_Seg()], None)})()
    assert eng.decode_window(object()) == "hello"


# ---- `yazses features` registry wiring -------------------------------------


def test_stt_parakeet_feature_writes_the_engine_key():
    from yazses.system.features import _registry

    d = next(d for d in _registry() if d.slug == "stt-parakeet")
    assert d.on_writes == (("stt", "engine", "parakeet", True),)
    assert d.off_writes == (("stt", "engine", "faster-whisper", True),)
    # Heavy feature: enable must know what to install.
    assert d.check_modules == ("onnx_asr",)
    assert any("onnx-asr" in p for p in d.pip_packages)


def test_stt_parakeet_feature_status_tracks_config():
    from yazses.config import Config
    from yazses.system.features import find_feature

    assert find_feature(Config(), "stt-parakeet").on is False
    cfg = Config()
    cfg.stt.engine = "parakeet"
    assert find_feature(cfg, "stt-parakeet").on is True
