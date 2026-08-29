"""Word-timestamp transcribe path for Prosody Ink (spec-prosody-ink, Phase 1).

``transcribe_words`` exposes faster-whisper's per-word timings so the prosody
postprocess can map inter-word pauses to paragraph breaks. The default
``transcribe`` fast path stays unchanged (no ``word_timestamps`` cost for
non-prosody users). Spec: design/specs/prosody-ink.md.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

# The transcription stack cannot be installed on every platform this project runs on:
# `ctranslate2` (via faster-whisper) publishes no FreeBSD wheel and no sdist at all, so
# `pip install -e .` cannot bring it in there. Skipping here rather than keeping a
# hand-maintained ignore list in the CI job means a new decoder test that forgets this
# line fails loudly on that platform instead of silently reducing coverage (#306).
pytest.importorskip("faster_whisper", reason="the decoder stack has no FreeBSD build")

from yazses.postprocess.prosody import Word
from yazses.stt.faster_whisper import FasterWhisperEngine


def _engine_with_model(model):
    eng = FasterWhisperEngine.__new__(FasterWhisperEngine)
    eng._model = model  # noqa: SLF001 — bypass model load in tests
    return eng


def _word(text, start, end):
    w = MagicMock()
    w.word = text
    w.start = start
    w.end = end
    return w


def test_transcribe_words_returns_text_and_aligned_words():
    seg = MagicMock()
    seg.text = " hello world"
    seg.words = [_word(" hello", 0.0, 0.4), _word(" world", 1.3, 1.7)]
    model = MagicMock()
    model.transcribe.return_value = ([seg], MagicMock())

    eng = _engine_with_model(model)
    text, words = eng.transcribe_words(np.zeros(16000, dtype="float32"))

    assert text == "hello world"
    assert [w.text for w in words] == ["hello", "world"]
    assert isinstance(words[0], Word)
    assert words[1].start == 1.3
    # word_timestamps must be requested on this path
    assert model.transcribe.call_args.kwargs.get("word_timestamps") is True


def test_transcribe_words_empty_audio_returns_empty():
    eng = _engine_with_model(MagicMock())
    text, words = eng.transcribe_words(np.array([], dtype="float32"))
    assert text == ""
    assert words == []


def test_transcribe_words_missing_word_timestamps_degrades_to_no_words():
    # If the model yields no per-word data, text still returns; words is empty.
    seg = MagicMock()
    seg.text = " hi there"
    seg.words = None
    model = MagicMock()
    model.transcribe.return_value = ([seg], MagicMock())

    eng = _engine_with_model(model)
    text, words = eng.transcribe_words(np.zeros(16000, dtype="float32"))
    assert text == "hi there"
    assert words == []
