"""Meeting-scribe labelling/formatting (ADR-v2-019) — pure diarize layer."""
from __future__ import annotations

from yazses.scribe.diarize import Turn, format_transcript, label_speakers, merge_turns


def test_label_speakers_first_appearance_order():
    labels = label_speakers(["b", "a", "b", "c"])
    assert labels == {"b": "Speaker 1", "a": "Speaker 2", "c": "Speaker 3"}


def test_label_speakers_self_is_you():
    labels = label_speakers(["spk0", "spk1", "spk0"], self_id="spk1")
    assert labels["spk1"] == "You"
    assert labels["spk0"] == "Speaker 1"


def test_merge_consecutive_same_speaker():
    turns = [Turn("a", "hello"), Turn("a", "there"), Turn("b", "hi")]
    merged = merge_turns(turns)
    assert merged == [Turn("a", "hello there"), Turn("b", "hi")]


def test_format_transcript_basic():
    turns = [Turn("s0", "good morning"), Turn("s1", "morning"), Turn("s0", "shall we start")]
    out = format_transcript(turns, self_id="s0")
    assert out == "You: good morning\nSpeaker 1: morning\nYou: shall we start"


def test_format_transcript_merges_then_labels():
    turns = [Turn("s0", "one"), Turn("s0", "two"), Turn("s1", "three")]
    out = format_transcript(turns)
    assert out == "Speaker 1: one two\nSpeaker 2: three"


def test_format_transcript_drops_blank_and_empty():
    assert format_transcript([]) == ""
    assert format_transcript([Turn("s0", "   "), Turn("s0", "")]) == ""


def test_feature_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    assert "scribe" in [f.slug for f in feature_status(Config())]
    assert Config().scribe.enabled is False
