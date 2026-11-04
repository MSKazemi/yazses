"""The phonetic corrector must not rewrite letters that are part of an identifier.

``/home/user/notes.txt`` became ``/home/Sara/notes.txt`` when "Sara" was in the vocabulary:
"user" and "Sara" share a phonetic key. Inside a path, URL, e-mail address, file name or
version the letters name a thing, so a rewrite points at a different one. Ordinary words
next to those spans must still be corrected, or the feature would be switched off by the fix.
"""
from __future__ import annotations

import pytest

from yazses.postprocess import phonetic
from yazses.postprocess.persian_text import normalise_persian, structured_spans

VOCAB = ["Sara", "Kubernetes", "Docker"]


@pytest.mark.parametrize(
    "text",
    [
        "/home/user/notes.txt",
        "open /home/user/notes.txt please",
        "src/user/main.py",
        r"C:\Users\user\notes.txt",
        "C:/Users/user/notes.txt",
        "https://example.com/user/page",
        "see www.user.example.com now",
        "mail user@example.com today",
        "open user.txt",
        "tagged v2.1.0",
        "python 3.13 release",
    ],
)
def test_identifier_shaped_text_is_left_byte_for_byte(text: str) -> None:
    assert phonetic.correct_text(text, VOCAB) == text


def test_an_ordinary_word_beside_a_path_is_still_corrected() -> None:
    out = phonetic.correct_text("the user said /home/user/notes.txt", VOCAB)
    assert out == "the Sara said /home/user/notes.txt"


def test_a_misheard_term_in_plain_prose_is_still_corrected() -> None:
    assert phonetic.correct_text("deploy to cubernetties", VOCAB) == "deploy to Kubernetes"


def test_structured_spans_cover_exactly_the_identifier() -> None:
    text = "see /home/user/notes.txt now"
    assert [text[a:b] for a, b in structured_spans(text)] == ["/home/user/notes.txt"]


def test_structured_spans_ignore_ordinary_words() -> None:
    assert structured_spans("get the file") == []
    assert structured_spans("") == []


def test_persian_normaliser_protection_is_unchanged_by_the_shared_pattern() -> None:
    """The shared pattern was split out of the Persian one; that one must not move."""
    text = "ك https://example.com/كتاب user@example.com /home/user/x.txt 3.13 ي"
    out = normalise_persian(text)
    assert "https://example.com/كتاب" in out
    assert "user@example.com" in out and "/home/user/x.txt" in out
    assert out.startswith("ک") and out.endswith("ی")
