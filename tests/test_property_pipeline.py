"""Property-based fuzz tests for the text post-processing pipeline (issue #115).

The pipeline is pure string handling over untrusted-ish input: whatever a
speech model emitted, including empty strings, repeated tokens, control
characters, mixed scripts, RTL text and very long transcripts. A crash here
takes down the daemon mid-dictation, so these tests assert invariants that
must hold for any input, not just the corpus cases in the other test files.

Anything a run turns up here that looks like a real bug belongs in
``contract/vectors/`` (see contract/README.md) so the Android port inherits
the fix before it is even written.
"""
from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from yazses.commands.grammar import (
    _RULES,
    IntentType,
    _normalise_numwords,
    _strip_outer_punct,
    classify,
)
from yazses.config import DisfluencyConfig
from yazses.postprocess.cleaner import clean_text
from yazses.postprocess.spacing import continuation_prefix
from yazses.postprocess.voice_punctuation import apply_voice_punctuation
from yazses.stt.filters.disfluency import filter_transcript

settings.register_profile(
    "pipeline", max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow]
)
settings.load_profile("pipeline")

# Characters a speech model can plausibly emit: ASCII, control characters,
# Persian (RTL is a first-class test language for this project), zero-width
# characters, and emoji/astral-plane code points.
_WILD_CHARS = st.one_of(
    st.characters(min_codepoint=0x20, max_codepoint=0x7E),
    st.characters(min_codepoint=0x00, max_codepoint=0x1F),
    st.sampled_from(list("سلام چطور هستید؟ من امروز به مدرسه رفتم")),
    st.sampled_from(["​", "‌", "‍", "﻿"]),
    st.sampled_from(["😀", "🎙", "𝕏", "🧵"]),
)

wild_text = st.text(alphabet=_WILD_CHARS, max_size=300)


@given(wild_text)
def test_clean_text_never_raises_and_returns_str(text):
    result = clean_text(text)
    assert isinstance(result, str)


@given(wild_text)
def test_clean_text_is_idempotent(text):
    once = clean_text(text)
    twice = clean_text(once)
    assert once == twice


@given(wild_text)
def test_filter_transcript_never_raises_and_returns_str(text):
    result = filter_transcript(text)
    assert isinstance(result.text, str)


@given(
    wild_text,
    st.booleans(),
    st.booleans(),
)
def test_filter_transcript_never_grows(text, collapse_repetitions, collapse_prolongations):
    config = DisfluencyConfig(
        collapse_repetitions=collapse_repetitions,
        collapse_prolongations=collapse_prolongations,
    )
    result = filter_transcript(text, config)
    assert len(result.text) <= len(text)


@given(wild_text)
def test_apply_voice_punctuation_never_raises_and_returns_str(text):
    result = apply_voice_punctuation(text)
    assert isinstance(result, str)


@given(wild_text, st.booleans())
def test_continuation_prefix_never_raises_and_returns_str(text, had_recent_injection):
    result = continuation_prefix(text, had_recent_injection=had_recent_injection)
    assert isinstance(result, str)


@given(wild_text)
def test_classify_never_raises_and_returns_str_fields(text):
    result = classify(text)
    assert isinstance(result.raw_text, str)
    assert isinstance(result.action, str)


@given(wild_text)
def test_classify_never_flips_to_a_command_by_accident(text):
    """A non-DICTATE result must be backed by an actual Tier-1 rule match.

    Without this, a weird input could flip classify() into COMMAND territory
    without any rule sanctioning it -- worse than a crash, per the issue: the
    phone would silently execute instead of dictating.
    """
    result = classify(text)
    if result.intent is IntentType.DICTATE:
        return
    normalised = _normalise_numwords(_strip_outer_punct(text))
    assert any(pattern.match(normalised) for pattern, _, _, _ in _RULES)


@given(st.text(alphabet=_WILD_CHARS, min_size=1000, max_size=5000))
@settings(max_examples=20)
def test_pipeline_survives_very_long_input(text):
    cleaned = clean_text(text)
    filtered = filter_transcript(cleaned)
    assert isinstance(filtered.text, str)
    assert isinstance(apply_voice_punctuation(filtered.text), str)
    assert isinstance(classify(filtered.text), object)
