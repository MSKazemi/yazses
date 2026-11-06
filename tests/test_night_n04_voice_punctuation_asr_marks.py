"""Voice punctuation on Whisper-shaped (already punctuated) transcripts.

Whisper punctuates on its own and punctuates a spoken mark as if it were a word, so
"hello comma world period" commonly decodes as "Hello, comma, world period.". At
8a72bbc6 the word-for-symbol swap typed "Hello,,, world." — the spoken mark plus the
decoder's guesses on both sides of it. Every expected value below is what the user
asked for by naming the mark; the inputs are synthetic.
"""
from __future__ import annotations

import pytest

from yazses.postprocess.voice_punctuation import apply_voice_punctuation


@pytest.mark.parametrize(
    ("decoded", "expected"),
    [
        # Decoder commas on both sides of a spoken comma.
        ("Hello, comma, world period.", "Hello, world."),
        # Decoder full stop before and after a spoken period.
        ("I went home. Period.", "I went home."),
        # Decoder mark glued to the end of the phrase.
        ("Is that right question mark?", "Is that right?"),
        ("Note colon, this", "Note: this"),
        ("Wow exclamation point!", "Wow!"),
        ("A semicolon, b", "A; b"),
        ("Stop full stop.", "Stop."),
    ],
)
def test_spoken_mark_replaces_the_decoders_guess(decoded: str, expected: str) -> None:
    assert apply_voice_punctuation(decoded) == expected


def test_a_different_sentence_mark_before_the_phrase_is_kept() -> None:
    # A "." or "?" that is not the inserted symbol may be meaningful (an abbreviation,
    # a real question) — only pause marks and the identical symbol are replaced.
    assert apply_voice_punctuation("Really? comma yes") == "Really?, yes"
    assert apply_voice_punctuation("Mr. comma Smith") == "Mr., Smith"


def test_consecutive_spoken_marks_are_all_kept() -> None:
    # One pass: a symbol this module just inserted is not treated as decoder
    # punctuation and swallowed by the next phrase.
    assert apply_voice_punctuation("a comma period") == "a,."
    assert apply_voice_punctuation("wait question mark exclamation mark") == "wait?!"


def test_decoder_mark_after_a_formatting_phrase_is_dropped() -> None:
    assert apply_voice_punctuation("Hello. New line. Next") == "Hello.\nNext"
    assert apply_voice_punctuation("One. New paragraph, two") == "One.\n\ntwo"


def test_two_spoken_tabs_stay_two_tabs() -> None:
    # The doubled-whitespace collapse used to squash "\t\t" into a single space.
    assert apply_voice_punctuation("a tab key tab key b") == "a\t\tb"


def test_plain_punctuated_text_without_phrases_is_untouched() -> None:
    text = "Hello, world. Is it? Yes: no; maybe!"
    assert apply_voice_punctuation(text) == text
