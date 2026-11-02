"""The built-in English prompt is sent only to decodes it is written for.

``BUILTIN_PROMPT`` ("The app is called YazSes.") is English. Whisper conditions its
decoder on whatever ``initial_prompt`` it is given, so with ``[stt] language = "fa"``
the English sentence biases a Persian decode, and when the decoder echoes its prompt
on noise (#598) English text lands in Persian dictation.

The rule: the built-in phrase is composed only when the configured language is unset,
auto-detect, or English. Any other language gets no built-in phrase. A prompt or
personal vocabulary the user wrote is sent exactly as before, whatever the language.

These tests need no model and no faster-whisper: they exercise the composition the
daemon performs, through the same ``Daemon._effective_initial_prompt`` the existing
prompt tests call.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from yazses.config import load_config
from yazses.core.daemon import Daemon
from yazses.stt.vocabulary import APP_NAME, BUILTIN_PROMPT, merge_initial_prompt


def _daemon(tmp_path, language: str, prompt: str = ""):
    cfg = load_config(None)
    cfg.stt.language = language
    cfg.stt.initial_prompt = prompt
    return SimpleNamespace(
        _config=cfg,
        _platform=SimpleNamespace(
            paths=SimpleNamespace(config_file=tmp_path / "config.toml")
        ),
        _personal_bias_terms=lambda: [],
    )


# --- the decision itself ---------------------------------------------------------------


@pytest.mark.parametrize("language", ["", "auto", "translate", "en", "EN", "en-US", "en_GB"])
def test_the_builtin_phrase_applies_to_unset_auto_and_english(language: str) -> None:
    from yazses.stt.vocabulary import builtin_prompt_applies

    assert builtin_prompt_applies(language)
    assert APP_NAME in (merge_initial_prompt(language=language) or "")


@pytest.mark.parametrize("language", ["fa", "fa-IR", "fa_IR", "zh", "de", "ar", "ur", "ru"])
def test_the_builtin_phrase_does_not_apply_to_a_non_english_language(language: str) -> None:
    from yazses.stt.vocabulary import builtin_prompt_applies

    assert not builtin_prompt_applies(language)
    assert merge_initial_prompt(language=language) is None


def test_merge_with_no_language_keeps_the_old_behaviour() -> None:
    # Callers that do not say a language (the learning analyser) still get the phrase.
    assert merge_initial_prompt() == BUILTIN_PROMPT


def test_a_user_prompt_is_sent_unchanged_for_a_non_english_language() -> None:
    assert merge_initial_prompt("کوبرنتیس", language="fa") == "کوبرنتیس"


# --- the daemon path, which is what the decoder actually receives ------------------------


def test_persian_decodes_do_not_receive_the_english_app_name(tmp_path) -> None:
    """The failing-before test. Before the fix this returned "The app is called YazSes."."""
    prompt = Daemon._effective_initial_prompt(_daemon(tmp_path, "fa"))
    assert prompt is None or APP_NAME not in prompt, prompt


@pytest.mark.parametrize("language", ["zh", "fa-IR", "de"])
def test_other_non_english_decodes_do_not_receive_the_english_app_name(tmp_path, language) -> None:
    prompt = Daemon._effective_initial_prompt(_daemon(tmp_path, language))
    assert prompt is None or APP_NAME not in prompt, prompt


@pytest.mark.parametrize("language", ["en", "", "auto"])
def test_english_and_auto_decodes_still_receive_the_app_name(tmp_path, language) -> None:
    prompt = Daemon._effective_initial_prompt(_daemon(tmp_path, language))
    assert prompt is not None and APP_NAME in prompt


def test_a_user_prompt_for_persian_is_sent_exactly_as_written(tmp_path) -> None:
    prompt = Daemon._effective_initial_prompt(_daemon(tmp_path, "fa", prompt="کوبرنتیس"))
    assert prompt == "کوبرنتیس"


def test_a_personal_vocabulary_for_persian_is_sent_without_the_english_sentence(tmp_path) -> None:
    (tmp_path / "vocabulary.txt").write_text("Zarquon", encoding="utf-8")
    prompt = Daemon._effective_initial_prompt(_daemon(tmp_path, "fa"))
    assert prompt is not None and "Zarquon" in prompt
    assert APP_NAME not in prompt


def test_an_english_user_prompt_still_gets_the_app_name_last(tmp_path) -> None:
    prompt = Daemon._effective_initial_prompt(_daemon(tmp_path, "en", prompt="Kubernetes"))
    assert prompt is not None
    assert prompt.startswith("Kubernetes")
    assert prompt.endswith(BUILTIN_PROMPT)
