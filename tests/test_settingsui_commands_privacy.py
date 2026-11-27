"""The Voice commands list and the privacy facts: both must match the product."""
from __future__ import annotations

import pytest

from yazses.commands.grammar import classify
from yazses.commands.types import IntentType
from yazses.config import Config
from yazses.settingsui import commands_view, privacy


@pytest.mark.parametrize("example", commands_view.EXAMPLES, ids=lambda e: e.phrase)
def test_every_listed_phrase_is_a_command_to_the_real_grammar(example):
    assert classify(example.phrase).intent is not IntentType.DICTATE


def test_search_matches_the_phrase_the_meaning_and_the_group():
    assert any(e.phrase == "undo" for e in commands_view.search("UNDO"))
    assert commands_view.search("navigation")
    assert commands_view.search("") == commands_view.EXAMPLES
    assert commands_view.search("zzzz") == ()


def _facts(cfg):
    return {f.label: f for f in privacy.privacy_facts(cfg)}


def test_a_fresh_install_reports_nothing_sent_or_kept():
    facts = _facts(Config())
    for label in ("AI cleanup", "Learning corpus", "Meeting audio"):
        assert facts[label].value in ("Off", "Deleted after a good transcript")
    assert facts["Remote dictation"].value == "Only while you run it"


def test_cleanup_says_the_text_stays_here_for_a_local_endpoint():
    cfg = Config()
    cfg.filters.disfluency.llm_enabled = True
    fact = _facts(cfg)["AI cleanup"]
    assert fact.value == "On"
    assert "this computer" in fact.detail


def test_an_allowed_remote_endpoint_is_reported_as_leaving_the_computer():
    cfg = Config()
    cfg.filters.disfluency.llm_enabled = True
    cfg.filters.disfluency.llm_allow_remote_endpoint = True
    cfg.filters.disfluency.llm_endpoint = "http://models.example:11434"
    fact = _facts(cfg)["AI cleanup"]
    assert fact.leaves
    assert "models.example" in fact.detail


def test_a_remote_endpoint_that_is_not_allowed_is_not_claimed_to_be_used():
    cfg = Config()
    cfg.filters.disfluency.llm_enabled = True
    cfg.filters.disfluency.llm_endpoint = "http://models.example:11434"
    assert not _facts(cfg)["AI cleanup"].leaves


def test_kept_meeting_audio_and_the_corpus_are_reported():
    cfg = Config()
    cfg.meeting.retain_audio = True
    cfg.learning.enabled = True
    facts = _facts(cfg)
    assert facts["Meeting audio"].value == "Kept"
    assert facts["Learning corpus"].value == "On"


def test_meeting_audio_kept_after_a_failure_is_said():
    assert "kept if processing fails" in _facts(Config())["Meeting audio"].detail


@pytest.mark.parametrize("audio, words", [(True, "including the audio"), (False, "text only")])
def test_the_corpus_says_whether_it_holds_audio(audio, words):
    cfg = Config()
    cfg.learning.capture_audio = audio
    assert words in _facts(cfg)["Learning corpus"].detail
