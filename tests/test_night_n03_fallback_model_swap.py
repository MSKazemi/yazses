"""The faster-whisper fallback never loads another engine's checkpoint by name.

`stt/factory.py` falls back to faster-whisper when the requested engine is unknown or
does not load. The fallback swapped a non-Whisper `[stt] model` for `base.en` only when
the *requested engine's* name was a substring of the model, so two configurations still
handed Whisper a checkpoint it cannot load:

- an unknown (typo'd) engine beside a Parakeet model: `engine = "parakeett"`,
  `model = "nemo-parakeet-tdt-0.6b-v2"` -- the unknown-engine path passed no
  `fallback_from` at all;
- a requested engine that is not the model's owner: `engine = "parakeet"` with
  `model = "moonshine/base"` and onnx-asr absent.

On a real machine both end in `ModelUnavailableError` -- "Speech model ... missing - run:
yazses model download nemo-parakeet-..." -- a fix that cannot work, for a cause that was
the engine setting. The fake model below records the name Whisper was asked to load.
"""
from __future__ import annotations

import logging
import sys

import pytest

# Same reason as tests/test_stt_factory.py: the decoder stack has no FreeBSD build (#306).
pytest.importorskip("faster_whisper", reason="the decoder stack has no FreeBSD build")

from yazses.config import SttConfig
from yazses.stt.factory import build_engine, describe_active_engine
from yazses.stt.faster_whisper import FasterWhisperEngine


@pytest.fixture
def fake_whisper(monkeypatch):
    """FasterWhisperEngine without a real model; records each model name it loads."""
    loaded: list[str] = []

    class _FakeModel:
        def __init__(self, model_name, device="cpu", compute_type="int8", **kwargs) -> None:
            loaded.append(model_name)

        def transcribe(self, audio, **kwargs):  # pragma: no cover - not exercised
            return [], None

    monkeypatch.setattr("yazses.stt.faster_whisper.WhisperModel", _FakeModel)
    return loaded


@pytest.fixture
def no_onnx_asr(monkeypatch):
    monkeypatch.setitem(sys.modules, "onnx_asr", None)  # import raises ModuleNotFoundError


def test_unknown_engine_beside_a_parakeet_model_falls_back_to_base_en(fake_whisper):
    engine = build_engine(SttConfig(engine="parakeett", model="nemo-parakeet-tdt-0.6b-v2"))
    assert isinstance(engine, FasterWhisperEngine)
    assert fake_whisper == ["base.en"], "Whisper was handed the Parakeet checkpoint"
    info = describe_active_engine(engine)
    assert info is not None
    assert info["model"] == "base.en"
    assert info["fallback_from"] == "parakeett"
    assert "not an engine YazSes knows" in info["fallback_reason"]


def test_unknown_engine_beside_a_moonshine_model_falls_back_to_base_en(fake_whisper):
    build_engine(SttConfig(engine="moonshine-v2", model="moonshine/tiny"))
    assert fake_whisper == ["base.en"]


def test_parakeet_fallback_swaps_a_moonshine_model_too(fake_whisper, no_onnx_asr, caplog):
    with caplog.at_level(logging.WARNING, logger="yazses.stt.factory"):
        build_engine(SttConfig(engine="parakeet", model="moonshine/base"))
    assert fake_whisper == ["base.en"]
    # The warning names the engine the model belongs to, not the one that failed.
    assert any(
        "belongs to the moonshine engine" in r.getMessage() for r in caplog.records
    )


def test_unknown_engine_keeps_a_whisper_model(fake_whisper):
    """Only another engine's checkpoint is swapped; a Whisper model the user chose stays."""
    build_engine(SttConfig(engine="whisperx", model="small"))
    assert fake_whisper == ["small"]


def test_the_configured_faster_whisper_engine_is_never_swapped(fake_whisper):
    """No fallback, no swap: an explicit faster-whisper config loads what it names."""
    build_engine(SttConfig(engine="faster-whisper", model="small.en"))
    assert fake_whisper == ["small.en"]
