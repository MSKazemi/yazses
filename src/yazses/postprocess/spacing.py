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

Since #501 (contract 7.1.0) the policy also knows Chinese and Japanese, which do not
put spaces between words. Two changes, both inert for text with no CJK in it:

* The full-width closers ``，。、；：！？）」』》】〉〕`` and the rest of the CJK
  punctuation set suppress the separator, so ``你好`` + ``，然后`` renders
  ``你好，然后`` and not ``你好 ，然后``. Full-width *opening* marks (``「`` ``（``)
  suppress it too, unlike their ASCII cousins: the glyph carries its own spacing.
* ``previous_tail`` -- the last character the previous burst typed -- lets the seam
  be judged from both sides. ``你好，世界。`` + ``今天测试。`` must not gain a space,
  and only the previous burst's last character can say that the seam is Han--Han.
  The rule is :func:`yazses.postprocess.cjk.needs_space`; a caller that does not
  pass ``previous_tail`` gets exactly the pre-7.1.0 answer.
"""
from __future__ import annotations

import unicodedata

from yazses.postprocess.cjk import is_cjk_punct, needs_space

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


def continuation_prefix(
    text: str, *, had_recent_injection: bool, previous_tail: str = ""
) -> str:
    """Return the separator to prepend before injecting ``text``.

    Returns a single space when ``text`` continues a recent dictation burst,
    except when its first visible character is closing punctuation (ASCII or
    Persian) or any CJK punctuation mark -- a full-width mark carries its own
    spacing, opening ones included. Returns "" for the first burst of a
    session, for empty text, or before such punctuation.

    ``previous_tail`` is the last character of the burst this one continues
    ("" when unknown). When given, the seam is also withheld where
    :func:`~yazses.postprocess.cjk.needs_space` says an unspaced script needs
    none -- between two Han clauses, or after a full-width mark such as ``。``.
    """
    if not had_recent_injection or not text:
        return ""
    first = _first_visible(text)
    if first in _NO_LEADING_SPACE_BEFORE or is_cjk_punct(first):
        return ""
    if previous_tail and first and not needs_space(previous_tail[-1:], first):
        return ""
    return " "
