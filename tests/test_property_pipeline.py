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
    CommandIntent,
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

# Applied per test as a decorator rather than via settings.load_profile(): a loaded
# profile becomes the *global* Hypothesis default for the whole pytest session, so it
# would silently relax deadlines and health checks for every property test added to this
# repo later. Bounded example count keeps CI fast (the ask in #115).
pipeline_settings = settings(
    max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow]
)

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


@pipeline_settings
@given(wild_text)
def test_clean_text_never_raises_and_returns_str(text):
    result = clean_text(text)
    assert isinstance(result, str)


@pipeline_settings
@given(wild_text)
def test_clean_text_is_idempotent(text):
    once = clean_text(text)
    twice = clean_text(once)
    assert once == twice


@pipeline_settings
@given(wild_text)
def test_filter_transcript_never_raises_and_returns_str(text):
    result = filter_transcript(text)
    assert isinstance(result.text, str)


@pipeline_settings
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


@pipeline_settings
@given(wild_text)
def test_apply_voice_punctuation_never_raises_and_returns_str(text):
    result = apply_voice_punctuation(text)
    assert isinstance(result, str)


@pipeline_settings
@given(wild_text, st.booleans())
def test_continuation_prefix_never_raises_and_returns_str(text, had_recent_injection):
    result = continuation_prefix(text, had_recent_injection=had_recent_injection)
    assert isinstance(result, str)


@pipeline_settings
@given(wild_text)
def test_classify_never_raises_and_returns_str_fields(text):
    result = classify(text)
    assert isinstance(result.raw_text, str)
    assert isinstance(result.action, str)


@pipeline_settings
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
    # Index rather than unpack: _RULES is an internal 4-tuple today, and a rule
    # gaining a field should not break this test for an unrelated reason.
    assert any(rule[0].match(normalised) for rule in _RULES)


@settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.text(alphabet=_WILD_CHARS, min_size=1000, max_size=5000))
def test_pipeline_survives_very_long_input(text):
    cleaned = clean_text(text)
    filtered = filter_transcript(cleaned)
    assert isinstance(filtered.text, str)
    assert isinstance(apply_voice_punctuation(filtered.text), str)
    # Assert the real contract. `isinstance(..., object)` is true of every value
    # in Python, so the original assertion here could not fail and proved nothing.
    intent = classify(filtered.text)
    assert isinstance(intent, CommandIntent)
    assert isinstance(intent.intent, IntentType)
    assert isinstance(intent.raw_text, str)
