"""Inter-utterance continuation spacing.

The daemon injects each hold-to-talk burst independently, after stripping
leading/trailing whitespace (see ``clean_text`` and ``filter_transcript``).
With no separator, consecutive bursts glue together at the boundary:

    "words together" + "I mean" -> "words togetherI mean"

``continuation_prefix`` computes the separator to prepend before a burst that
continues a recent dictation. Policy: a single space, suppressed when the new
burst opens with closing punctuation (so we get "word." not "word .").

Since #551 the policy is script-aware. The suppression set is no longer
ASCII-only: the Persian closing marks — U+060C (،), U+061F (؟), U+061B (؛) —
and the closing guillemet U+00BB (») suppress the separator exactly like their
Latin cousins, so "کلمه" + "، بعداً" renders "کلمه، بعداً" instead of the
stray-space "کلمه ، بعداً". The probe also skips invisible format characters
(Unicode category ``Cf``: ZWNJ, ZWJ, the bidi controls, the Arabic letter
mark, the byte-order mark) before deciding, because a character the user
cannot see cannot carry the "this burst opens with closing punctuation"
decision. A burst whose first *visible* character is an ordinary word still
gets its space — joining across a leading ZWNJ is a normalization decision
(``persian_text`` strips boundary ZWNJ), not a spacing one.
"""
from __future__ import annotations

import unicodedata

# Closing punctuation that should hug the preceding word — never preceded by a
# space. Opening delimiters (quotes, "(", "[", U+00AB «) are intentionally
# absent: a new clause starting with one still wants a leading space.
_NO_LEADING_SPACE_BEFORE = frozenset(".,!?;:)]}…%،؟؛»")


def _first_visible(text: str) -> str:
    """First character of *text* that is not an invisible format character.

    Unicode general category ``Cf`` covers the zero-width family a dictation
    burst can legitimately begin with — U+200C ZWNJ joining into the previous
    word, U+200D ZWJ, U+200E/U+200F marks, the U+202A–U+202E embedding and
    override controls, the U+2066–U+2069 isolates, U+061C, U+FEFF — none of
    which renders. Probing past them (#551) stops an invisible character from
    either hiding closing punctuation from the suppression rule or masking it.
    """
    for ch in text:
        if unicodedata.category(ch) != "Cf":
            return ch
    return ""


def continuation_prefix(text: str, *, had_recent_injection: bool) -> str:
    """Return the separator to prepend before injecting ``text``.

    Returns a single space when ``text`` continues a recent dictation burst,
    except when its first visible character is closing punctuation. Returns
    "" for the first burst of a session, for empty text, or before closing
    punctuation.
    """
    if not had_recent_injection or not text:
        return ""
    if _first_visible(text) in _NO_LEADING_SPACE_BEFORE:
        return ""
    return " "
