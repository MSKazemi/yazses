"""Built-in STT vocabulary — the app's own name is always primed into Whisper.

"YazSes" is a coined word Whisper has never seen, so it mis-transcribes the
spoken name ("yes ses", "yaz says", ...). `merge_initial_prompt` prepends a short
natural phrase containing the canonical spelling to every decode's
`initial_prompt`, merged ahead of the user's configured/personal vocabulary.
"""
from __future__ import annotations

from yazses.stt.vocabulary import APP_NAME, BUILTIN_PROMPT, merge_initial_prompt


def test_builtin_prompt_contains_app_name():
    assert APP_NAME in BUILTIN_PROMPT


def test_merge_always_includes_app_name_even_with_no_parts():
    merged = merge_initial_prompt()
    assert merged is not None
    assert APP_NAME in merged


def test_merge_includes_app_name_when_part_is_none_or_blank():
    merged = merge_initial_prompt(None, "   ", "")
    assert merged is not None
    assert APP_NAME in merged
    # No stray double spaces from the blank parts.
    assert "  " not in merged


def test_merge_puts_the_builtin_phrase_after_the_user_prompt():
    merged = merge_initial_prompt("kubernetes terraform")
    assert APP_NAME in merged
    assert "kubernetes terraform" in merged
    # User vocabulary first, built-in context last. Whisper keeps only the last 223
    # prompt tokens and drops the front without a word, so the phrase that must
    # survive is the one nearest the audio --- see
    # tests/test_the_builtin_prompt_survives_the_decoder_window.py.
    assert merged.index("kubernetes") < merged.index(APP_NAME)


def test_merge_joins_multiple_parts():
    merged = merge_initial_prompt("Notes.", "Kubernetes, kubectl")
    assert "Notes." in merged
    assert "Kubernetes, kubectl" in merged
