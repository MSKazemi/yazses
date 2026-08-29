"""`[stt] language` — dictating in something other than English.

Live dictation used to hardcode ``language="en"`` in every decode path, so the
multilingual docs described a key that did not exist and was silently dropped by
configcheck. These tests pin the wiring end to end: the config value reaches
every faster-whisper decode, ``""`` means auto-detect, the translate path still
auto-detects by design, and the two ways a user can configure something
impossible (an ``.en`` model, or the English-only Parakeet engine) each produce
an honest warning instead of quiet nonsense.
"""
from __future__ import annotations

import logging

import numpy as np
import pytest

# The transcription stack cannot be installed on every platform this project runs on:
# `ctranslate2` (via faster-whisper) publishes no FreeBSD wheel and no sdist at all, so
# `pip install -e .` cannot bring it in there. Skipping here rather than keeping a
# hand-maintained ignore list in the CI job means a new decoder test that forgets this
# line fails loudly on that platform instead of silently reducing coverage (#306).
pytest.importorskip("faster_whisper", reason="the decoder stack has no FreeBSD build")

from yazses.config import SttConfig
from yazses.stt.factory import build_engine
from yazses.stt.faster_whisper import FasterWhisperEngine


@pytest.fixture
def calls(monkeypatch):
    """Capture the kwargs every ``WhisperModel.transcribe`` call receives."""
    seen: list[dict] = []

    class _FakeSegment:
        text = "hallo welt"
        words: list = []

    class _FakeModel:
        # **kwargs so the fake accepts `local_files_only`, which the real loader
        # passes on its first (cache-only) attempt; without it these fakes would
        # silently exercise the download fallback instead of the real path.
        def __init__(self, model_name, device="cpu", compute_type="int8", **kwargs) -> None:
            pass

        def transcribe(self, audio, **kwargs):
            seen.append(kwargs)
            return [_FakeSegment()], None

    monkeypatch.setattr("yazses.stt.faster_whisper.WhisperModel", _FakeModel)
    return seen


AUDIO = np.ones(16000, dtype=np.float32)


# ── the language actually reaches the decoder ────────────────────────────────

def test_configured_language_reaches_transcribe(calls):
    FasterWhisperEngine(model_name="small", language="de").transcribe(AUDIO)
    assert calls == [{"language": "de"}]


def test_configured_language_reaches_transcribe_words(calls):
    FasterWhisperEngine(model_name="small", language="fr").transcribe_words(AUDIO)
    assert calls[0]["language"] == "fr"
    assert calls[0]["word_timestamps"] is True


def test_configured_language_reaches_streaming_window(calls):
    """The streaming path decoded English regardless — a silent bug for de/fr/es."""
    FasterWhisperEngine(model_name="small", language="es").decode_window(AUDIO)
    assert calls == [{"language": "es"}]


def test_default_is_still_english(calls):
    """The English fast path must be unchanged for everyone who set nothing."""
    FasterWhisperEngine(model_name="base.en").transcribe(AUDIO)
    assert calls == [{"language": "en"}]


# ── auto-detect and translate ────────────────────────────────────────────────

@pytest.mark.parametrize("language", ["", "   "])
def test_empty_language_omits_the_kwarg_so_whisper_autodetects(calls, language):
    FasterWhisperEngine(model_name="small", language=language).transcribe(AUDIO)
    assert calls == [{}]


def test_translate_task_never_pins_a_language(calls):
    """ADR-v2-014 X→English auto-detects the source; a pin would defeat it."""
    engine = FasterWhisperEngine(model_name="small", language="de")
    engine.transcribe(AUDIO, task="translate")
    assert calls == [{"task": "translate"}]
    assert "language" not in calls[0]


def test_initial_prompt_still_rides_along(calls):
    FasterWhisperEngine(model_name="small", language="de").transcribe(
        AUDIO, initial_prompt="YazSes"
    )
    assert calls == [{"language": "de", "initial_prompt": "YazSes"}]


# ── the factory wires config → engine ────────────────────────────────────────

def test_factory_passes_language_from_config(calls):
    engine = build_engine(SttConfig(model="small", language="it"))
    assert isinstance(engine, FasterWhisperEngine)
    engine.transcribe(AUDIO)
    assert calls == [{"language": "it"}]


def test_config_default_language_is_english():
    assert SttConfig().language == "en"


# ── honest warnings for impossible combinations ──────────────────────────────

def test_en_model_with_non_english_language_warns(calls, caplog):
    """`.en` checkpoints have no language tokens — this cannot work, so say so."""
    with caplog.at_level(logging.WARNING, logger="yazses.stt.factory"):
        build_engine(SttConfig(model="base.en", language="de"))
    assert "English-only" in caplog.text
    assert "drop the .en suffix" in caplog.text


def test_multilingual_model_with_non_english_language_is_silent(calls, caplog):
    with caplog.at_level(logging.WARNING, logger="yazses.stt.factory"):
        build_engine(SttConfig(model="small", language="de"))
    assert "English-only" not in caplog.text


def test_en_model_with_english_language_is_silent(calls, caplog):
    with caplog.at_level(logging.WARNING, logger="yazses.stt.factory"):
        build_engine(SttConfig(model="base.en", language="en"))
    assert "English-only" not in caplog.text
