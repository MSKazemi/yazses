"""A long Moonshine burst must not hand upstream a sub-0.1 s tail piece.

`MoonshineEngine._decode_long` splits a burst past upstream's 64 s ceiling into
~60 s pieces. Each piece went straight to `_decode_one`, bypassing the 0.1 s floor
that `_decode` enforces for a whole burst. A burst whose length is a hair over a
multiple of the chunk (e.g. 120.05 s) left a 0.05 s remainder, and upstream's bare
`assert 0.1 < num_seconds < 64` turned the user's two-minute dictation into an
`AssertionError` and lost all of it.

Synthetic, offline: the `moonshine_onnx` module is replaced by a double that
mirrors upstream's batching and both of its size assertions; no model is loaded.
"""

from __future__ import annotations

import sys
import types

import numpy as np
import pytest

from yazses.stt.moonshine import DEFAULT_MODEL, MoonshineEngine

_RATE = 16000


class _Cfg:
    engine, model = "moonshine", "moonshine/base"
    device, compute_type, language, initial_prompt = "cpu", "int8", "en", ""


@pytest.fixture
def strict_moonshine(monkeypatch):
    """A `moonshine_onnx` double that enforces upstream's shape and duration asserts."""
    calls: list[np.ndarray] = []
    module = types.ModuleType("moonshine_onnx")

    class MoonshineOnnxModel:
        def __init__(self, model_name=DEFAULT_MODEL):
            self.model_name = model_name

    def transcribe(audio, model=DEFAULT_MODEL):
        calls.append(np.asarray(audio))
        batched = np.asarray(audio)[None, ...]          # upstream's load_audio
        assert len(batched.shape) == 2, "audio should be of shape [batch, samples]"
        num_seconds = batched.size / _RATE               # upstream's assert_audio_size
        assert 0.1 < num_seconds < 64, (
            "Moonshine models support audio segments that are between 0.1s and 64s"
        )
        return ["piece"]

    module.MoonshineOnnxModel = MoonshineOnnxModel
    module.transcribe = transcribe
    monkeypatch.setitem(sys.modules, "moonshine_onnx", module)
    return calls


@pytest.mark.parametrize("seconds", [120.05, 120.0 + 1 / _RATE, 60.0 * 3 + 0.1])
def test_a_tiny_remainder_after_splitting_is_not_sent_upstream(strict_moonshine, seconds):
    audio = np.zeros(int(round(seconds * _RATE)), dtype=np.float32)

    text = MoonshineEngine(_Cfg()).transcribe(audio)

    assert strict_moonshine, "the long burst should still reach the model"
    for piece in strict_moonshine:
        assert 0.1 < piece.size / _RATE < 64
    # The full-length pieces are all still decoded; only the empty tail is dropped.
    assert text.split() == ["piece"] * len(strict_moonshine)
    assert len(strict_moonshine) == int(seconds // 60)


def test_a_long_burst_with_a_real_tail_still_decodes_the_tail(strict_moonshine):
    """The fix drops only what upstream cannot take, not a tail with speech in it."""
    audio = np.zeros(int(130 * _RATE), dtype=np.float32)

    MoonshineEngine(_Cfg()).transcribe(audio)

    assert [round(p.size / _RATE) for p in strict_moonshine] == [60, 60, 10]
