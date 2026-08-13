"""Moonshine STT engine behind the `SttEngine` seam (#74).

The decode path is exercised against a fake model so no weights are downloaded,
but the *contract* is checked against the real `moonshine_onnx` package, which is
a dev dependency: its `transcribe` signature and its audio-size assertion are the
two things this adapter is shaped around, and pinning them means an upstream
change fails here rather than in someone's dictation.
"""

from __future__ import annotations

import sys
import types

import numpy as np
import pytest

from yazses.stt.factory import _build_raw_engine
from yazses.stt.moonshine import (
    DEFAULT_MODEL,
    MAX_SECONDS,
    MIN_SECONDS,
    MoonshineEngine,
    _first_text,
)


class _Cfg:
    def __init__(self, engine="moonshine", model="moonshine/base"):
        self.engine, self.model = engine, model
        self.device, self.compute_type, self.language = "cpu", "int8", "en"
        self.initial_prompt = ""


def _audio(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * 16000), dtype=np.float32)


@pytest.fixture
def fake_moonshine(monkeypatch):
    """Replace the module so no model is downloaded; record what it was given."""
    calls = []
    module = types.ModuleType("moonshine_onnx")

    class MoonshineOnnxModel:
        def __init__(self, model_name=DEFAULT_MODEL):
            self.model_name = model_name

    def transcribe(audio, model=DEFAULT_MODEL):
        calls.append(np.asarray(audio))
        return ["hello world"]          # upstream returns decode_batch(...) — a list

    module.MoonshineOnnxModel = MoonshineOnnxModel
    module.transcribe = transcribe
    monkeypatch.setitem(sys.modules, "moonshine_onnx", module)
    return calls


# ---- the upstream contract this adapter is shaped around -------------------


def test_real_package_transcribe_signature_is_what_we_call():
    """`transcribe(audio, model)` — pinned against the installed package."""
    import inspect

    import moonshine_onnx

    params = list(inspect.signature(moonshine_onnx.transcribe).parameters)
    assert params[:2] == ["audio", "model"]


def test_real_package_enforces_the_audio_bounds_we_mirror():
    """0.1s–64s, enforced with a bare assert — hence our guards."""
    import importlib
    import inspect

    module = importlib.import_module("moonshine_onnx.transcribe")
    source = inspect.getsource(module.assert_audio_size)
    assert "0.1" in source and "64" in source
    assert "[batch, samples]" in source, "audio must be 2-D"


def test_our_bounds_match_upstreams():
    assert (MIN_SECONDS, MAX_SECONDS) == (0.1, 64.0)


# ---- decoding --------------------------------------------------------------


def test_a_batch_result_is_unwrapped_to_a_string(fake_moonshine):
    """Upstream returns a list; using it directly types "['hello world']"."""
    assert MoonshineEngine(_Cfg()).transcribe(_audio(2)) == "hello world"


def test_audio_is_reshaped_to_batch_samples(fake_moonshine):
    MoonshineEngine(_Cfg()).transcribe(_audio(2))
    assert fake_moonshine[0].ndim == 2, "upstream asserts [batch, samples]"
    assert fake_moonshine[0].shape[0] == 1


@pytest.mark.parametrize("result,expected", [
    (["a"], "a"), ("a", "a"), ([], ""), (["  padded  "], "padded"),
])
def test_first_text_handles_every_shape_upstream_might_return(result, expected):
    assert _first_text(result) == expected


# ---- the bounds, which are reachable in normal use -------------------------


def test_a_key_tap_below_the_floor_returns_empty_not_an_assertion(fake_moonshine):
    """Upstream would raise AssertionError; that reads as a crash to a user."""
    assert MoonshineEngine(_Cfg()).transcribe(_audio(0.05)) == ""
    assert fake_moonshine == [], "must not reach the model at all"


def test_empty_audio_is_safe(fake_moonshine):
    assert MoonshineEngine(_Cfg()).transcribe(np.zeros(0, dtype=np.float32)) == ""


def test_a_long_burst_is_split_rather_than_rejected(fake_moonshine):
    """Past 64s upstream asserts. A long paragraph must still transcribe."""
    text = MoonshineEngine(_Cfg()).transcribe(_audio(150))
    assert len(fake_moonshine) > 1, "should have been split into several calls"
    for chunk in fake_moonshine:
        seconds = chunk.size / 16000
        assert MIN_SECONDS < seconds < MAX_SECONDS, f"chunk of {seconds}s violates upstream"
    assert text == "hello world hello world hello world"[:len(text)]


# ---- model selection -------------------------------------------------------


def test_a_foreign_checkpoint_name_falls_back_with_a_warning(fake_moonshine, caplog):
    """`[stt] model` often still holds the previous engine's checkpoint."""
    import logging

    with caplog.at_level(logging.WARNING):
        engine = MoonshineEngine(_Cfg(model="base.en"))
    assert engine._model_name == DEFAULT_MODEL
    assert any("not a Moonshine checkpoint" in r.getMessage() for r in caplog.records)


def test_a_moonshine_checkpoint_is_honoured(fake_moonshine):
    assert MoonshineEngine(_Cfg(model="moonshine/tiny"))._model_name == "moonshine/tiny"


# ---- the seam --------------------------------------------------------------


def test_the_factory_selects_moonshine(fake_moonshine):
    assert isinstance(_build_raw_engine(_Cfg()), MoonshineEngine)


def test_a_missing_dependency_falls_back_to_whisper_rather_than_crashing(monkeypatch):
    """Dictation must still come up if the optional dep is absent."""
    import builtins

    real_import = builtins.__import__

    def fail_moonshine(name, *a, **kw):
        if name.startswith("moonshine_onnx"):
            raise ModuleNotFoundError("No module named 'moonshine_onnx'", name="moonshine_onnx")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fail_moonshine)
    monkeypatch.setattr(
        "yazses.stt.factory._build_faster_whisper", lambda stt, fallback_from="": "whisper"
    )
    assert _build_raw_engine(_Cfg()) == "whisper"


def test_word_timings_are_reported_as_absent_not_invented(fake_moonshine):
    text, words = MoonshineEngine(_Cfg()).transcribe_words(_audio(2))
    assert text == "hello world"
    assert words == [], "Moonshine exposes no timings; inventing them would be worse"


def test_the_engine_satisfies_the_SttEngine_protocol_exactly(fake_moonshine):
    """The daemon passes `sample_rate` positionally and always passes `task`.

    A keyword-only signature type-checks fine in isolation and then raises on the
    first real dictation — mypy caught this before a user could.
    """
    import inspect

    from yazses.stt.base import SttEngine

    engine = MoonshineEngine(_Cfg())
    for name in ("transcribe", "transcribe_words"):
        expected = list(inspect.signature(getattr(SttEngine, name)).parameters)
        actual = list(inspect.signature(getattr(engine, name)).parameters)
        assert actual == [p for p in expected if p != "self"], f"{name} diverges from the protocol"

    # And the call the daemon actually makes must work.
    assert engine.transcribe(_audio(2), 16000, "a prompt", "transcribe") == "hello world"
