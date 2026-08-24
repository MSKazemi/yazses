"""`[stt] condition_on_previous_text` — the knob the decode 2x2 said users need.

Measured (`docs/benchmarks.md`, `paper/results/probes/decode-determinism-*.json`,
five decodes per arm over 200 LibriSpeech utterances): conditioning each 30-second
window on the text of the one before it is what makes `large-v3` wander between
4.84 % and 6.21 % WER across *identical* runs, because on roughly 1.5 % of
utterances it sends the model into a repetition loop. On `base.en`, the shipped
model, it is the better setting on both splits and already bit-reproducible.

So the default does not move and the key exists for the large-checkpoint case. What
these tests pin is the thing that has already gone wrong once here: `[stt] language`
was a documented key that reached nothing, because three decode paths each
hardcoded their own value. A setting that reaches one path out of three is worse
than one that reaches none, because it looks like it works.
"""
from __future__ import annotations

import inspect

import numpy as np
import pytest

from yazses.config import SttConfig
from yazses.stt.factory import build_engine
from yazses.stt.faster_whisper import FasterWhisperEngine

AUDIO = np.ones(16000, dtype=np.float32)

#: Every public decode entry point on the engine, and how to call it.
DECODE_PATHS = {
    "transcribe": lambda e: e.transcribe(AUDIO),
    "transcribe_words": lambda e: e.transcribe_words(AUDIO),
    "decode_window": lambda e: e.decode_window(AUDIO),
}


@pytest.fixture
def calls(monkeypatch):
    """Capture the kwargs every ``WhisperModel.transcribe`` call receives."""
    seen: list[dict] = []

    class _FakeSegment:
        text = "the quick brown fox"
        words: list = []

    class _FakeModel:
        def __init__(self, model_name, device="cpu", compute_type="int8", **kwargs) -> None:
            pass

        def transcribe(self, audio, **kwargs):
            seen.append(kwargs)
            return [_FakeSegment()], None

    monkeypatch.setattr("yazses.stt.faster_whisper.WhisperModel", _FakeModel)
    return seen


# ── the default is unchanged, and unchanged means *silent* ───────────────────

@pytest.mark.parametrize("path", sorted(DECODE_PATHS))
def test_the_default_sends_nothing_at_all(calls, path: str) -> None:
    """Pinning a library default explicitly freezes it at today's value.

    `beam_size = 0` means "say nothing and let faster-whisper choose" for exactly
    this reason. Sending ``condition_on_previous_text=True`` would look identical
    today and would silently override a future upstream change, so the default
    path must send the kwarg not at all -- which also proves every published
    benchmark still describes the shipped decode.
    """
    DECODE_PATHS[path](FasterWhisperEngine(model_name="base.en"))
    assert "condition_on_previous_text" not in calls[0]


# ── turning it off reaches every decode path, not one of three ───────────────

@pytest.mark.parametrize("path", sorted(DECODE_PATHS))
def test_turning_it_off_reaches_every_decode_path(calls, path: str) -> None:
    engine = FasterWhisperEngine(model_name="base.en", condition_on_previous_text=False)
    DECODE_PATHS[path](engine)
    assert calls[0].get("condition_on_previous_text") is False, (
        f"{path} decoded without the flag the user set. It must build its kwargs "
        "through `_decode_kwargs`, which is the single seam every path shares."
    )


def test_no_decode_path_is_missing_from_this_test() -> None:
    """Guard the guard: the check above iterates a hand-written set.

    A hand-written set is the defect this repository has shipped before -- the
    parametrisation stays green when a fourth decode method is added and never
    calls `_decode_kwargs`. So the set is checked against the class.
    """
    public = {
        name
        for name, fn in inspect.getmembers(FasterWhisperEngine, inspect.isfunction)
        if not name.startswith("_") and "audio" in inspect.signature(fn).parameters
    }
    assert public == set(DECODE_PATHS), (
        f"FasterWhisperEngine decodes audio through {sorted(public)}, but this test "
        f"only drives {sorted(DECODE_PATHS)}. Add the new path here and make sure it "
        "builds its kwargs through `_decode_kwargs`."
    )


def test_every_decode_path_builds_its_kwargs_through_the_shared_seam() -> None:
    """The behavioural test above can be satisfied by copying the line into each
    method, which is precisely how `[stt] language` came to be dropped by three
    call sites at once. Read the source and require the seam."""
    for name in DECODE_PATHS:
        src = inspect.getsource(getattr(FasterWhisperEngine, name))
        assert "_decode_kwargs" in src, (
            f"{name} does not call `_decode_kwargs`. Every decode path shares it so "
            "that a new `[stt]` key reaches all three the day it is added."
        )


# ── the config value gets there ──────────────────────────────────────────────

def test_the_config_key_reaches_the_engine(calls) -> None:
    engine = build_engine(SttConfig(model="base.en", condition_on_previous_text=False))
    engine.transcribe(AUDIO)
    assert calls[0].get("condition_on_previous_text") is False


def test_the_config_default_is_the_shipped_behaviour(calls) -> None:
    """`SttConfig()` is what an unconfigured machine runs, and every number on
    `docs/benchmarks.md` was measured with conditioning on."""
    assert SttConfig().condition_on_previous_text is True
    build_engine(SttConfig(model="base.en")).transcribe(AUDIO)
    assert "condition_on_previous_text" not in calls[0]


def test_a_config_object_without_the_attribute_still_builds(calls) -> None:
    """`build_engine` is handed duck-typed config objects by tests and by the
    meeting/recimport paths; a missing attribute must mean the default, not a crash."""
    class _Old:
        engine = "faster-whisper"
        model = "base.en"
        device = "cpu"
        compute_type = "int8"
        language = "en"

    build_engine(_Old()).transcribe(AUDIO)
    assert "condition_on_previous_text" not in calls[0]


# ── the translate path keeps its own rule ────────────────────────────────────

def test_translate_still_carries_the_flag(calls) -> None:
    """`task="translate"` drops the *language* by design (ADR-v2-014 auto-detects
    the source). Conditioning is unrelated to that and must survive."""
    engine = FasterWhisperEngine(model_name="small", condition_on_previous_text=False)
    engine.transcribe(AUDIO, task="translate")
    assert calls[0]["task"] == "translate"
    assert calls[0].get("condition_on_previous_text") is False
