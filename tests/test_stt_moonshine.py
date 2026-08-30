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

from tests.decoder_stack import needs_moonshine
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
        # Mirror upstream's *pipeline*, not just its assertion. The real function is
        #     audio = load_audio(audio)   # -> audio[None, ...], unconditionally
        #     assert_audio_size(audio)    # -> assert len(audio.shape) == 2
        # so it is the caller's un-batched array that must be 1-D. The previous double
        # recorded the argument and asserted nothing, which is how a caller that passed
        # `(1, N)` — and therefore failed on every real utterance — stayed green here.
        calls.append(np.asarray(audio))
        batched = np.asarray(audio)[None, ...]
        assert len(batched.shape) == 2, "audio should be of shape [batch, samples]"
        return ["hello world"]          # upstream returns decode_batch(...) — a list

    module.MoonshineOnnxModel = MoonshineOnnxModel
    module.transcribe = transcribe
    monkeypatch.setitem(sys.modules, "moonshine_onnx", module)
    return calls


# ---- the upstream contract this adapter is shaped around -------------------


@needs_moonshine
def test_real_package_transcribe_signature_is_what_we_call():
    """`transcribe(audio, model)` — pinned against the installed package."""
    import inspect

    import moonshine_onnx

    params = list(inspect.signature(moonshine_onnx.transcribe).parameters)
    assert params[:2] == ["audio", "model"]


@needs_moonshine
def test_real_package_enforces_the_audio_bounds_we_mirror():
    """0.1s–64s, enforced with a bare assert — hence our guards."""
    import importlib
    import inspect

    module = importlib.import_module("moonshine_onnx.transcribe")
    source = inspect.getsource(module.assert_audio_size)
    assert "0.1" in source and "64" in source
    assert "[batch, samples]" in source, "the shape assertion is still there"


def test_our_bounds_match_upstreams():
    assert (MIN_SECONDS, MAX_SECONDS) == (0.1, 64.0)


@needs_moonshine
def test_real_package_batches_the_audio_itself() -> None:
    """The contract that was never pinned, and the whole bug.

    `assert_audio_size` says `[batch, samples]`, so the adapter reshaped to `(1, N)`
    before calling — but `transcribe` runs `load_audio` first, and `load_audio` ends in
    `return audio[None, ...]` for any non-path input. The assertion therefore describes
    the array *after* upstream has batched it, and a caller that batches it too fails on
    every utterance. Pinned against the installed package, not remembered.
    """
    import importlib

    tm = importlib.import_module("moonshine_onnx.transcribe")
    one_d = np.zeros(16000, dtype=np.float32)
    assert tm.load_audio(one_d).shape == (1, 16000)
    assert tm.load_audio(one_d.reshape(1, -1)).shape == (1, 1, 16000)


@needs_moonshine
def test_the_real_package_rejects_a_pre_batched_array() -> None:
    """State the failure the way the machine stated it, with no model download."""
    import importlib

    tm = importlib.import_module("moonshine_onnx.transcribe")
    one_d = np.zeros(16000, dtype=np.float32)
    tm.assert_audio_size(tm.load_audio(one_d))          # the fix: fine
    with pytest.raises(AssertionError, match=r"\[batch, samples\]"):
        tm.assert_audio_size(tm.load_audio(one_d.reshape(1, -1)))


# ---- decoding --------------------------------------------------------------


def test_a_batch_result_is_unwrapped_to_a_string(fake_moonshine):
    """Upstream returns a list; using it directly types "['hello world']"."""
    assert MoonshineEngine(_Cfg()).transcribe(_audio(2)) == "hello world"


def test_audio_is_passed_un_batched(fake_moonshine):
    """The regression: `[batch, samples]` describes what upstream checks, not what
    it is given. `load_audio` adds the axis, so handing it `(1, N)` makes `(1, 1, N)`
    and every utterance fails the assertion the reshape was written to satisfy."""
    MoonshineEngine(_Cfg()).transcribe(_audio(2))
    assert fake_moonshine[0].ndim == 1, (
        "upstream batches the array itself in load_audio; a pre-batched one becomes 3-D"
    )


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
