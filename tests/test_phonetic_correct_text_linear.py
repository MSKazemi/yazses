"""``phonetic.correct_text`` must not scan every protected span for every token.

The structured-span regexes were made linear, but the loop that asked "is this token inside a
span?" still walked the whole span list per token: tokens x spans. The membership test is now one
bisect over merged, sorted spans.

Two kinds of check, neither of which reads a clock:

* an operation count: how many spans ``correct_text`` visits, which must not depend on how many
  tokens there are;
* a golden comparison against ``_reference_correct_text``, a verbatim copy of the quadratic
  implementation it replaced, over a corpus of real shapes and over hand-built span lists
  (empty, inverted, overlapping, touching, unsorted) that the real matcher never produces but the
  old ``any(a <= pos < b)`` contract defined.
"""
from __future__ import annotations

import re

import pytest

from yazses.postprocess import persian_text, phonetic

VOCAB = ["Sara", "Kubernetes", "Docker", "GitHub", "Git", "Mohsen"]
KNOWN = {"get", "the", "file", "had", "go", "ahead"}


def _reference_correct_text(text, vocab, spans, *, max_distance=0.34, known=None):
    """The pre-fix implementation, kept as the oracle. Quadratic on purpose."""
    if not text or not vocab:
        return text

    def _fix(m):
        if any(a <= m.start() < b for a, b in spans):
            return m.group(0)
        return phonetic.correct_word(m.group(0), vocab, max_distance=max_distance, known=known)

    return re.sub(r"[A-Za-z]+", _fix, text)


_CORPUS = [
    "",
    "   ",
    "get the file",
    "go ahead and try it, we had a great time",
    "deploy to cubernetties with dokker and githab",
    "the user said /home/user/notes.txt",
    "open /home/user/notes.txt please and tell sarah",
    "src/user/main.py and docs/guide/install.md",
    r"C:\Users\user\notes.txt then D:\پروژه\فایل.txt",
    "C:/Program Files/app/run.exe",
    "see https://example.com/user/page?c=d#f and www.user.example.com now",
    "mail sara+tag@example.com or user@example.co.uk, thanks sarra",
    "tagged v2.1.0 on python 3.13 with v1 and kubernetis",
    "~/code/yazses/src/x.py and ../up/one.py ./here/x",
    "a-b-c.tar.gz, my_file-name.v2.tar.gz; README.md",
    "فایل notes.txt را در پوشه src/app/main.py باز کن sarra",
    "ایمیل sara@example.com و نسخه 3.13 و و/یا /usr/local/bin/python3.13 dokker",
    "中文 user.txt 日本語 cubernetties 한국어 /home/user/x",
    "user.txt",
    "hello.Next sentence about dokker",
    "x" * 300 + " sarra " + "/a/user/b " * 20,
    " ".join(f"word{'x' * (i % 3)} see /home/user/f{i}.txt githab" for i in range(40)),
]


@pytest.mark.parametrize("text", _CORPUS)
@pytest.mark.parametrize("known", [None, KNOWN])
def test_real_spans_give_the_same_output_as_the_quadratic_loop(text, known):
    spans = persian_text.structured_spans(text)
    want = _reference_correct_text(text, VOCAB, spans, known=known)
    assert phonetic.correct_text(text, VOCAB, known=known) == want


@pytest.mark.parametrize("max_distance", [0.0, 0.2, 0.34, 0.6, 1.0])
def test_max_distance_is_honoured_identically(max_distance):
    text = "cubernetties and dokker near /home/user/x.txt and sarra"
    spans = persian_text.structured_spans(text)
    want = _reference_correct_text(text, VOCAB, spans, max_distance=max_distance)
    assert phonetic.correct_text(text, VOCAB, max_distance=max_distance) == want


_TEXT = "alpha beta /gamma delta epsilon zeta eta theta iota kappa lambda"
_N = len(_TEXT)
_STARTS = [m.start() for m in re.finditer(r"[A-Za-z]+", _TEXT)]
_ENDS = [m.end() for m in re.finditer(r"[A-Za-z]+", _TEXT)]

_HAND_BUILT = {
    "none": [],
    "empty-span-at-token-start": [(_STARTS[2], _STARTS[2])],
    "inverted-span": [(_ENDS[3], _STARTS[3])],
    "whole-text": [(0, _N)],
    "one-char-at-token-start": [(_STARTS[1], _STARTS[1] + 1)],
    "ends-exactly-at-token-start": [(0, _STARTS[3])],
    "starts-exactly-at-token-end": [(_ENDS[3], _N)],
    "touching-spans": [(0, 10), (10, 20), (20, 30)],
    "overlapping-spans": [(0, 15), (10, 25), (12, 14), (40, 50), (45, 48)],
    "nested-spans": [(5, 50), (10, 20), (30, 40)],
    "unsorted-spans": [(40, 50), (0, 6), (20, 30), (10, 12)],
    "duplicate-spans": [(10, 20), (10, 20), (10, 20)],
    "past-the-end": [(_N - 2, _N + 100), (_N + 5, _N + 9)],
    "negative-start": [(-5, 4)],
    "every-token-covered": list(zip(_STARTS, _ENDS)),
    "alternate-tokens": [(s, e) for k, (s, e) in enumerate(zip(_STARTS, _ENDS)) if k % 2],
    "tuples-and-lists": [[0, 6], (20, 30)],
}


@pytest.mark.parametrize("name", sorted(_HAND_BUILT))
def test_hand_built_span_lists_match_the_old_any_contract(name, monkeypatch):
    spans = _HAND_BUILT[name]
    vocab = ["Alpha", "Gamma", "Delta", "Kappa", "Lamda", "Zeta"]
    monkeypatch.setattr(persian_text, "structured_spans", lambda _t: list(spans))
    want = _reference_correct_text(_TEXT, vocab, spans)
    assert phonetic.correct_text(_TEXT, vocab) == want


def test_every_span_position_pair_agrees_with_the_old_contract(monkeypatch):
    """Exhaustive over a short text: every span (a, b) in range against every token start."""
    text = "ab cd ef"
    vocab = ["Abe", "Cod", "Eff"]
    n = len(text)
    for a in range(-1, n + 2):
        for b in range(-1, n + 2):
            spans = [(a, b)]
            monkeypatch.setattr(persian_text, "structured_spans", lambda _t, s=spans: list(s))
            assert phonetic.correct_text(text, vocab) == _reference_correct_text(
                text, vocab, spans
            ), (a, b)


# ---- operation count, not wall clock ------------------------------------------------------


_REAL_STRUCTURED_SPANS = persian_text.structured_spans  # captured before any monkeypatch


class _CountingSpans(list):
    """A span list that counts how many span entries are handed out by iteration."""

    visits = 0

    def __iter__(self):
        for item in list.__iter__(self):
            type(self).visits += 1
            yield item


def _visits(text: str, monkeypatch) -> tuple[int, int, int]:
    """(span visits, spans, tokens) for ``correct_text(text, ["Sara"])``."""
    real = _REAL_STRUCTURED_SPANS
    _CountingSpans.visits = 0
    monkeypatch.setattr(persian_text, "structured_spans", lambda t: _CountingSpans(real(t)))
    phonetic.correct_text(text, ["Sara"])
    return (
        _CountingSpans.visits,
        len(real(text)),
        len(re.findall(r"[A-Za-z]+", text)),
    )


@pytest.mark.parametrize("count", [25, 100, 400])
def test_span_visits_do_not_scale_with_tokens_times_spans(count, monkeypatch):
    text = " ".join(f"see /home/user/f{i}.txt and more words" for i in range(count))
    visits, spans, tokens = _visits(text, monkeypatch)
    assert spans >= count and tokens >= 7 * count  # the corpus really has both
    # Each span is handed out once (to build the sorted index); the old loop made up to
    # tokens x spans visits, which was 12 600 / 50 200 / 800 800 for 50 / 100 / 400 spans.
    assert visits <= spans


def test_doubling_the_input_doubles_the_span_visits(monkeypatch):
    def unit(n: int) -> str:
        return " ".join(f"open /home/user/f{i}.txt now" for i in range(n))

    small, _, _ = _visits(unit(100), monkeypatch)
    large, _, _ = _visits(unit(200), monkeypatch)
    assert large == 2 * small  # linear; the quadratic loop gave 4x
