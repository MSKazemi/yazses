"""The phonetic corrector must not rewrite letters that are part of an identifier.

``/home/user/notes.txt`` became ``/home/Sara/notes.txt`` when "Sara" was in the vocabulary:
"user" and "Sara" share a phonetic key. Inside a path, URL, e-mail address, file name or
version the letters name a thing, so a rewrite points at a different one. Ordinary words
next to those spans must still be corrected, or the feature would be switched off by the fix.
"""
from __future__ import annotations

import time

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


# ---- the same patterns must stay linear in the length of the text --------------------------
#
# 69d9b771 made the relative-path and file-name alternatives (and, through the shared
# pattern, the e-mail one) open-ended runs that were retried at every character, so
# `correct_text(s, ["Sara"])` cost 6-8 s on a 20 000-character word. Ratios, not
# milliseconds (see tests/test_disfluency_filter.py): quadratic growth is 16x for 4x the
# input, linear is 4x; the bound sits between, and the minimum over several samples rides
# out a loaded machine.

_SCALE = 4
_BASE_CHARS = 1500
_MAX_RATIO = 9.0  # linear ~4, quadratic ~16
_UNITS = {
    "word": "a",
    "cjk": "中文",
    "hyphenated": "a-",
    "dotted": "a-.",
    "persian": "ك",
    "email-like": "a.b+c",
}


def _best_seconds(fn, arg: str, samples: int = 5) -> float:
    best = float("inf")
    for _ in range(samples):
        start = time.perf_counter()
        fn(arg)
        best = min(best, time.perf_counter() - start)
    return best


@pytest.mark.parametrize("name", sorted(_UNITS))
def test_structured_spans_cost_grows_linearly_with_the_text(name: str) -> None:
    unit = _UNITS[name]
    small = unit * (_BASE_CHARS // len(unit))
    large = unit * (_BASE_CHARS * _SCALE // len(unit))
    ratio = _best_seconds(structured_spans, large) / max(
        _best_seconds(structured_spans, small), 1e-6
    )
    assert ratio < _MAX_RATIO, (
        f"{_SCALE}x the text cost {ratio:.1f}x for {name!r}: not linear "
        f"(linear ~{_SCALE}, quadratic ~{_SCALE**2})"
    )


def test_a_long_word_does_not_stall_the_phonetic_corrector() -> None:
    def run(text: str) -> None:
        phonetic.correct_text(text, VOCAB)

    ratio = _best_seconds(run, "a" * (_BASE_CHARS * _SCALE)) / max(
        _best_seconds(run, "a" * _BASE_CHARS), 1e-6
    )
    assert ratio < _MAX_RATIO, f"{_SCALE}x the text cost {ratio:.1f}x: not linear"


# Recorded from the base commit (1af96caa), before the bound: the spans protected for
# realistic paths, file names, e-mail addresses and versions, Windows and Persian text
# included. Quirks are recorded too ("C:/Program Files" splits at the space; "و/یا" has a
# relative-path shape) because the point is that the bound changed nothing.
_RECORDED_SPANS = [
    ("open /home/user/notes.txt please", ["/home/user/notes.txt"]),
    ("src/user/main.py and docs/guide/install.md", ["src/user/main.py", "docs/guide/install.md"]),
    (
        "C:\\Users\\user\\notes.txt then D:\\پروژه\\فایل.txt",
        ["C:\\Users\\user\\notes.txt", "D:\\پروژه\\فایل.txt"],
    ),
    ("C:/Program Files/app/run.exe", ["C:/Program", "Files/app/run.exe"]),
    (
        "see https://example.com/a/b?c=d#f and www.example.org",
        ["https://example.com/a/b?c=d#f", "www.example.org"],
    ),
    (
        "mail sara+tag@example.com or user@example.co.uk",
        ["sara+tag@example.com", "user@example.co.uk"],
    ),
    ("tagged v2.1.0 on python 3.13 with v1", ["v2.1.0", "3.13", "v1"]),
    (
        "~/code/yazses/src/x.py and ../up/one.py ./here/x",
        ["/code/yazses/src/x.py", "../up/one.py", "./here/x"],
    ),
    (
        "a-b-c.tar.gz, my_file-name.v2.tar.gz; README.md",
        ["a-b-c.tar", "my_file-name.v2", "tar.gz", "README.md"],
    ),
    ("node_modules/.bin/tsc", ["node_modules/.bin/tsc"]),
    ("فایل notes.txt را در پوشه src/app/main.py باز کن", ["notes.txt", "src/app/main.py"]),
    (
        "ایمیل sara@example.com و نسخه 3.13 و و/یا /usr/local/bin/python3.13",
        ["sara@example.com", "3.13", "و/یا", "/usr/local/bin/python3.13"],
    ),
    ("--out.txt and -a.txt", ["out.txt", "a.txt"]),
    ("the well-known user said hello.Next sentence", ["hello.Next"]),
    ("1.2-x/y and 1.2.x/y", ["1.2", "-x/y", "1.2", ".x/y"]),
]


@pytest.mark.parametrize("text, expected", _RECORDED_SPANS)
def test_the_bound_protects_exactly_what_it_protected_before(
    text: str, expected: list[str]
) -> None:
    assert [text[a:b] for a, b in structured_spans(text)] == expected


def test_names_at_the_file_system_limit_are_still_protected() -> None:
    stem = "n" * 255
    for text in (f"{stem}.txt", f"src/{stem}", f"{stem}/x.py"):
        spans = structured_spans(text)
        assert spans and spans[0][0] == 0 and spans[-1][1] == len(text)
