"""Hallucination Guard (ADR-v2-025) — pure detectors + drop decision."""
from __future__ import annotations

from dataclasses import dataclass

from yazses.postprocess.hallucination import (
    is_ghost_phrase,
    is_repetition_loop,
    segment_is_hallucination,
    should_drop,
)


@dataclass
class _Cfg:
    enabled: bool = True
    drop_ghost_phrases: bool = True
    drop_loops: bool = True
    no_speech_threshold: float = 0.6
    logprob_threshold: float = -1.0
    compression_ratio_threshold: float = 2.4


# ---- ghost phrases ---------------------------------------------------------

def test_ghost_phrase_whole_transcript():
    assert is_ghost_phrase("Thanks for watching!")
    assert is_ghost_phrase("please subscribe")


def test_ghost_phrase_not_substring():
    # a real sentence that merely contains 'thank you' is NOT a ghost
    assert not is_ghost_phrase("thank you for the detailed report on the incident")


def test_ghost_phrase_ignores_legit_short_speech():
    assert not is_ghost_phrase("thank you")  # ambiguous single phrase — never auto-dropped


# ---- repetition loops ------------------------------------------------------

def test_repetition_loop_single_word():
    assert is_repetition_loop("the the the the")


def test_repetition_loop_phrase():
    assert is_repetition_loop("i love it i love it i love it")


def test_no_false_loop_on_normal_text():
    assert not is_repetition_loop("the quick brown fox jumps over the lazy dog")


def test_short_text_not_a_loop():
    assert not is_repetition_loop("hello there")


# ---- segment signal gate ---------------------------------------------------

def test_segment_high_no_speech_is_hallucination():
    assert segment_is_hallucination(0.9, -0.2, 1.5, _Cfg())


def test_segment_low_logprob_is_hallucination():
    assert segment_is_hallucination(0.1, -1.5, 1.5, _Cfg())


def test_segment_high_compression_is_hallucination():
    assert segment_is_hallucination(0.1, -0.2, 3.0, _Cfg())


def test_segment_clean_is_not_hallucination():
    assert not segment_is_hallucination(0.1, -0.2, 1.5, _Cfg())


def test_segment_none_signals_skipped():
    assert not segment_is_hallucination(None, None, None, _Cfg())


# ---- should_drop + config gate ---------------------------------------------

def test_should_drop_respects_disabled():
    assert should_drop("thanks for watching", _Cfg(enabled=False)) is False


def test_should_drop_ghost_and_loop():
    assert should_drop("please subscribe", _Cfg())
    assert should_drop("no no no no", _Cfg())


def test_should_drop_leaves_real_text():
    assert should_drop("the meeting is at three pm tomorrow", _Cfg()) is False


def test_should_drop_toggles():
    assert should_drop("thanks for watching", _Cfg(drop_ghost_phrases=False)) is False
    assert should_drop("the the the", _Cfg(drop_loops=False)) is False


def test_feature_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    assert "hallucination" in [f.slug for f in feature_status(Config())]
    assert Config().hallucination.enabled is False
