"""The prompt Whisper actually receives is the *tail*, not what we composed.

``WhisperModel.max_length`` is 448 and faster-whisper's ``get_prompt`` splices the
prompt in as ``previous_tokens[-(max_length // 2 - 1):]`` — it keeps the last 223
tokens and discards the front. Nothing rejects a longer prompt and nothing warns;
the cut is silent and lands mid-word.

`stt/vocabulary.py` used to put the built-in phrase **first**, which is exactly the
position that gets cut, while its own docstring said the name was "always primed".
Measured with the real ``base.en`` tokenizer, a 120-term personal vocabulary
overflows by 25 tokens and takes the whole of "The app is called YazSes." with it —
so for anyone with a substantial vocabulary the one thing this module exists to do
had stopped happening, with nothing said.

These tests assert the ordering directly (no model needed) and then re-derive the
overflow arithmetic against a real Whisper tokenizer when one is cached, because the
number 223 is only meaningful if it is still faster-whisper's.
"""

from __future__ import annotations

import glob
import os

import pytest

from tests.decoder_stack import needs_faster_whisper
from yazses.stt.vocabulary import (
    BUILTIN_PROMPT,
    PROMPT_TOKEN_BUDGET,
    merge_initial_prompt,
)


def test_the_builtin_phrase_is_last_so_the_truncation_cannot_reach_it() -> None:
    """The whole fix. Truncation keeps the tail, so the phrase that must survive
    belongs at the end — for every prompt length and every language, with nothing
    estimated."""
    merged = merge_initial_prompt("Kubernetes EuroHPC", "ctranslate2")
    assert merged is not None
    assert merged.endswith(BUILTIN_PROMPT), merged
    assert not merged.startswith(BUILTIN_PROMPT), (
        "the built-in phrase is back at the front, which is the half Whisper drops"
    )


def test_the_builtin_phrase_is_still_present_with_no_vocabulary() -> None:
    assert merge_initial_prompt() == BUILTIN_PROMPT
    assert merge_initial_prompt(None, "", "   ") == BUILTIN_PROMPT


@needs_faster_whisper
def test_the_budget_still_matches_faster_whispers_own_arithmetic() -> None:
    """A hand-copied constant is the artefact that drifts. `max_length` is a plain
    attribute set in the constructor, so it is read off the class rather than off a
    loaded model — no download, no weights."""
    import inspect

    from faster_whisper.transcribe import WhisperModel

    source = inspect.getsource(WhisperModel)
    assert "self.max_length = 448" in source, "max_length moved; re-derive the budget"
    assert "previous_tokens[-(self.max_length // 2 - 1) :]" in source, (
        "get_prompt no longer keeps the tail of the prompt; re-check which end is cut"
    )
    assert PROMPT_TOKEN_BUDGET == 448 // 2 - 1


def _cached_tokenizer():
    pattern = os.path.expanduser(
        "~/.cache/huggingface/hub/models--Systran--faster-whisper-*/snapshots/*/tokenizer.json"
    )
    found = sorted(glob.glob(pattern))
    if not found:
        pytest.skip("no faster-whisper tokenizer in the local cache")
    tokenizers = pytest.importorskip("tokenizers")
    return tokenizers.Tokenizer.from_file(found[0])


def test_a_large_vocabulary_no_longer_costs_the_builtin_phrase() -> None:
    """The reproduction, run through a real tokenizer: compose an over-long prompt,
    apply the decoder's own keep-the-tail rule, and check what is left."""
    tokenizer = _cached_tokenizer()
    vocabulary = " ".join(f"Term{i}" for i in range(1, 121))
    merged = merge_initial_prompt(vocabulary)
    assert merged is not None

    ids = tokenizer.encode(" " + merged.strip(), add_special_tokens=False).ids
    assert len(ids) > PROMPT_TOKEN_BUDGET, (
        "the fixture stopped overflowing, so it no longer exercises the truncation"
    )

    kept = ids[-PROMPT_TOKEN_BUDGET:]
    builtin = tokenizer.encode(" " + BUILTIN_PROMPT.strip(), add_special_tokens=False).ids
    assert kept[-len(builtin):] == builtin, (
        "the built-in name priming was cut off by the decoder's prompt window"
    )


class _Ids:
    def __init__(self, ids: list[int]) -> None:
        self.ids = ids


class _Tokenizer:
    """Counts one token per whitespace-separated word — enough to drive the
    threshold, and it keeps the test off the real model."""

    def encode(self, text: str, add_special_tokens: bool = True) -> _Ids:
        return _Ids(list(range(len(text.split()))))


class _Model:
    hf_tokenizer = _Tokenizer()


def _engine():
    from yazses.stt.faster_whisper import FasterWhisperEngine

    engine = FasterWhisperEngine.__new__(FasterWhisperEngine)
    engine._model = _Model()
    return engine


@needs_faster_whisper
def test_an_over_long_prompt_is_reported_once_not_every_burst(caplog) -> None:
    """Hold-to-talk decodes many times a minute. A warning per burst is a warning
    the user turns off, so it is emitted once per distinct prompt."""
    engine = _engine()
    prompt = " ".join(f"Term{i}" for i in range(PROMPT_TOKEN_BUDGET + 40))

    with caplog.at_level("WARNING", logger="yazses.stt.faster_whisper"):
        for _ in range(3):
            assert engine._prompt_kwargs(prompt) == {"initial_prompt": prompt}

    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1, [r.getMessage() for r in warnings]
    assert "40" in warnings[0].getMessage(), warnings[0].getMessage()


@needs_faster_whisper
def test_a_prompt_that_fits_says_nothing(caplog) -> None:
    engine = _engine()
    with caplog.at_level("WARNING", logger="yazses.stt.faster_whisper"):
        engine._prompt_kwargs(merge_initial_prompt("Kubernetes EuroHPC"))
    assert [r.getMessage() for r in caplog.records if r.levelname == "WARNING"] == []


@needs_faster_whisper
def test_a_prompt_that_cannot_be_measured_is_still_passed_through(caplog) -> None:
    """The warning is a courtesy; the decode is the product. A tokenizer that
    raises, or a backend that has none, must not cost the user their prompt."""

    class _Broken:
        def encode(self, text, add_special_tokens=True):
            raise RuntimeError("no vocabulary loaded")

    engine = _engine()
    engine._model.hf_tokenizer = _Broken()
    with caplog.at_level("WARNING", logger="yazses.stt.faster_whisper"):
        assert engine._prompt_kwargs("hello") == {"initial_prompt": "hello"}
    assert [r.getMessage() for r in caplog.records if r.levelname == "WARNING"] == []

    engine = _engine()
    engine._model = object()
    assert engine._prompt_kwargs("hello") == {"initial_prompt": "hello"}
    assert engine._prompt_kwargs(None) == {}
