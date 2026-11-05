"""The pluggable STT engine factory (`[stt] engine`, stt/factory.py).

Guard-and-fallback contract: whatever the config says, dictation must come up —
on faster-whisper if the requested engine can't load — and every fallback is
logged honestly (never a silent engine switch).
"""
from __future__ import annotations

import logging
import sys

import pytest

# The transcription stack cannot be installed on every platform this project runs on:
# `ctranslate2` (via faster-whisper) publishes no FreeBSD wheel and no sdist at all, so
# `pip install -e .` cannot bring it in there. Skipping here rather than keeping a
# hand-maintained ignore list in the CI job means a new decoder test that forgets this
# line fails loudly on that platform instead of silently reducing coverage (#306).
pytest.importorskip("faster_whisper", reason="the decoder stack has no FreeBSD build")

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


# ---- the fallback must not hide why the requested engine is not running -------------
#
# Parakeet v3 lists `de`. With the stt-parakeet extra missing, the fallback swaps the
# (Parakeet) model for the English-only `base.en`, which the language guard then refuses.
# That refusal used to be the only thing the ERROR state and the toast carried: it told
# the user to change a model they never chose and never named the extra.

_V3 = "nemo-parakeet-tdt-0.6b-v3"


def _fake_parakeet_load(monkeypatch, exc: BaseException) -> None:
    def _load(self):
        raise exc

    monkeypatch.setattr("yazses.stt.parakeet.ParakeetEngine._load", _load)


def test_parakeet_missing_extra_with_german_leads_with_the_real_cause(
    fake_whisper, monkeypatch
):
    from yazses.stt.errors import LanguageUnsupportedError, ModelUnavailableError

    _fake_parakeet_load(monkeypatch, ModuleNotFoundError("no onnx_asr", name="onnx_asr"))
    with pytest.raises(LanguageUnsupportedError) as info:
        build_engine(SttConfig(engine="parakeet", model=_V3, language="de"))
    exc = info.value
    assert isinstance(exc, ModelUnavailableError)  # the daemon's ERROR-hold type
    text = str(exc)
    # Leads with the requested engine's failure and its fix, not the fallback model.
    assert text.splitlines()[0].startswith("The parakeet engine is not running because")
    assert "onnx_asr" in text
    assert "yazses features enable stt-parakeet" in text
    assert "'de'" in text
    assert "multilingual Whisper model" in text
    assert exc.language == "de"
    title, body = exc.notification()
    assert title == "YazSes cannot start dictation"
    assert "yazses features enable stt-parakeet" in body and "'de'" in body
    assert fake_whisper == []  # nothing was loaded


def test_parakeet_load_failure_with_german_names_the_failure(fake_whisper, monkeypatch):
    from yazses.stt.errors import LanguageUnsupportedError

    _fake_parakeet_load(monkeypatch, RuntimeError("/home/someone/private/path boom"))
    with pytest.raises(LanguageUnsupportedError) as info:
        build_engine(SttConfig(engine="parakeet", model=_V3, language="de"))
    text = str(info.value)
    assert text.splitlines()[0].startswith("The parakeet engine is not running because")
    assert "failed to load (RuntimeError" in text
    assert "'de'" in text
    assert "/home/someone" not in text  # the reason carries the type only


@pytest.mark.parametrize("language", ["en", ""])
def test_parakeet_fallback_unchanged_for_english_and_autodetect(
    fake_whisper, monkeypatch, language
):
    _fake_parakeet_load(monkeypatch, ModuleNotFoundError("x", name="onnx_asr"))
    engine = build_engine(SttConfig(engine="parakeet", model=_V3, language=language))
    assert isinstance(engine, FasterWhisperEngine)
    assert fake_whisper[0][0] == "base.en"
    assert engine.fallback_from == "parakeet"
    assert "yazses features enable stt-parakeet" in engine.fallback_reason


def test_parakeet_fallback_unchanged_for_a_multilingual_whisper_model(
    fake_whisper, monkeypatch
):
    _fake_parakeet_load(monkeypatch, RuntimeError("boom"))
    engine = build_engine(SttConfig(engine="parakeet", model="small", language="en"))
    assert isinstance(engine, FasterWhisperEngine)
    assert fake_whisper[0][0] == "small"
    assert engine.fallback_from == "parakeet"


def test_plain_language_refusal_message_is_unchanged():
    from yazses.stt.errors import LanguageUnsupportedError

    exc = LanguageUnsupportedError("faster-whisper", "base.en", "de", "why")
    assert str(exc).startswith("YazSes will not transcribe 'de' with faster-whisper")
    assert "[stt] language = 'de'" in exc.notification()[1]


def test_moonshine_fallback_unchanged_for_english(fake_whisper, monkeypatch):
    def _boom(self, config):
        raise RuntimeError("boom")

    monkeypatch.setattr("yazses.stt.moonshine.MoonshineEngine.__init__", _boom)
    engine = build_engine(SttConfig(engine="moonshine", language="en"))
    assert isinstance(engine, FasterWhisperEngine)
    assert engine.fallback_from == "moonshine"
