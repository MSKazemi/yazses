"""Apply prosodic punctuation to finished dictation text (pure) — ADR-v2-104.

``punctuate_from_prosody`` decides *where* a mark goes; this module puts it into text that has
already been through the recognizer, ``clean_text`` and every other transform. Three properties
matter more than coverage, because a punctuation pass that mangles prose is worse than none:

* **Whitespace is preserved.** Marks are spliced in at word ends; the text is never split and
  re-joined, so line breaks and spacing that earlier transforms produced survive.
* **Existing punctuation wins.** Whisper usually punctuates already. A word that ends in
  punctuation is left alone, so this never produces ``,.`` or ``..``; it only fills gaps.
* **No alignment, no change.** Word timings come from the decoder and the text from many later
  transforms (number normalisation can turn two words into one). When the counts disagree the
  pauses cannot be trusted to belong to the right words, so the text is returned untouched.

Pitch cues (``terminal_rise``) are accepted but the daemon does not supply them yet, so today
this is pause-driven only and never writes a question mark.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from yazses.prosodypunct.punctuate import boundary_marks

_TOKEN = re.compile(r"\S+")
#: Closing brackets and quotes that may follow a word's last letter ("(see above)").
_CLOSERS = ")]}\"'”’»"
#: A word that ends in one of these already carries its punctuation.
_ALREADY = ".,;:!?…。，、！？"


@dataclass(frozen=True)
class PunctuationResult:
    """The punctuated text plus metadata-only counts (never the words themselves)."""
    text: str
    sentences: int
    commas: int


def _insertion_point(token: str) -> int | None:
    """Index in ``token`` at which a mark may go (its end), or None when it must not take one."""
    core_end = len(token)
    while core_end > 0 and token[core_end - 1] in _CLOSERS:
        core_end -= 1
    if core_end == 0:
        return None
    last = token[core_end - 1]
    if last in _ALREADY or not last.isalnum():
        return None
    return len(token)


def punctuate_text(
    text: str,
    word_spans: Sequence[tuple[float, float]],
    *,
    sentence_pause_ms: float = 700.0,
    comma_pause_ms: float = 250.0,
    terminal_rise: Sequence[bool] | None = None,
) -> PunctuationResult:
    """Insert ``. , ?`` into ``text`` from the silence between spoken words. Pure.

    ``word_spans`` is one ``(start_s, end_s)`` per word, in the order spoken, aligned with the
    whitespace-separated words of ``text``. The mark after word *i* depends on the gap before
    word *i+1*; the last word has no following gap, so the end of the utterance is never
    touched (the recognizer's own final punctuation stands). After an inserted ``.`` or ``?`` a
    wholly lower-case next word is capitalised.
    """
    matches = list(_TOKEN.finditer(text))
    if len(matches) < 2 or len(matches) != len(word_spans):
        return PunctuationResult(text, 0, 0)

    pause_after_ms = [
        max(0.0, (word_spans[i + 1][0] - word_spans[i][1]) * 1000.0)
        for i in range(len(word_spans) - 1)
    ] + [0.0]
    marks = boundary_marks(
        len(matches), pause_after_ms, terminal_rise=terminal_rise,
        sentence_pause_ms=sentence_pause_ms, comma_pause_ms=comma_pause_ms,
    )

    pieces: list[str] = []
    cursor = 0
    sentences = commas = 0
    capitalise_next = False
    for m, mark in zip(matches, marks):
        token = m.group()
        if capitalise_next and token[0].isalpha() and token == token.lower():
            token = token[0].upper() + token[1:]
        capitalise_next = False
        point = _insertion_point(token) if mark else None
        if point is not None:
            token = token[:point] + mark + token[point:]
            if mark == ",":
                commas += 1
            else:
                sentences += 1
                capitalise_next = True
        pieces.append(text[cursor:m.start()])
        pieces.append(token)
        cursor = m.end()
    pieces.append(text[cursor:])
    return PunctuationResult("".join(pieces), sentences, commas)
