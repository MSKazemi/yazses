"""Script-aware joining, measuring and breaking of unspaced CJK text (#501). Pure.

Most of the text pipeline was written for languages that put a space between words,
and it shows in one recurring shape: two pieces of text are glued back together with
``" ".join``. For English that is exactly right. For Chinese and Japanese, which do not
separate words with spaces, it inserts a space at every seam -- ``你好，世界。 今天测试。``
-- and anything that measures text by ``str.split()`` sees a whole sentence as one word.

This module answers the questions those call sites need, in one place, with no
dependencies, so each caller can stay byte-identical for text that holds no CJK:

* :func:`needs_space` -- does a space belong at the seam between two pieces?
* :func:`join_pieces` -- ``" ".join`` that knows about unspaced scripts.
* :func:`display_width` -- caption width, counting a full-width character as two.
* :func:`break_units` -- the units a line may be broken between, with the separator
  that sits in front of each.
* :func:`glue_word_tokens` -- regroup a recogniser's word tokens so a Latin word or a
  number decoded in pieces inside Mandarin comes back whole.

**English is unchanged by construction.** Every function here returns what the
whitespace-only code returned whenever neither side of a seam is CJK; the CJK branch
is reached only through a character in the ranges below. That is what lets a fix to a
Mandarin seam ship without moving any English output.

What this module does *not* claim: it does not segment Chinese into words (that needs a
dictionary or a model), and the convention it applies at a Han--Latin seam (keep the
space, as in ``今天测试 YazSes``) is the common typographic one, not a rule every
publisher follows.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence

# --- character classes ------------------------------------------------------------

#: Han ideographs, including the astral extensions B..H and the compatibility
#: supplement. The astral planes matter: a surname such as 𠮷 (U+20BB7) is outside
#: the BMP, and a range check that stops at U+FFFF calls it "not Chinese".
_HAN = (
    (0x2E80, 0x2FDF),    # CJK radicals supplement, Kangxi radicals
    (0x31C0, 0x31EF),    # CJK strokes
    (0x3400, 0x4DBF),    # extension A
    (0x4E00, 0x9FFF),    # unified ideographs
    (0xF900, 0xFAFF),    # compatibility ideographs
    (0x20000, 0x2FA1F),  # extensions B..F, I + compatibility supplement
    (0x30000, 0x323AF),  # extensions G, H
)

#: Other letters of scripts written without inter-word spaces: kana (full and half
#: width), Bopomofo, the ideographic iteration and number marks, and the full-width
#: Latin letters and digits that appear inside Chinese text (``ＡＢＣ１２３``).
_UNSPACED_OTHER = (
    (0x3005, 0x3007),    # 々 〆 〇
    (0x3021, 0x3029),    # Hangzhou numerals
    (0x3031, 0x3035),    # kana repeat marks
    (0x3038, 0x303C),
    (0x3040, 0x309F),    # hiragana
    (0x30A0, 0x30FF),    # katakana
    (0x3100, 0x312F),    # bopomofo
    (0x31A0, 0x31BF),    # bopomofo extended
    (0x31F0, 0x31FF),    # katakana phonetic extensions
    (0xFF10, 0xFF19),    # full-width digits
    (0xFF21, 0xFF3A),    # full-width Latin capitals
    (0xFF41, 0xFF5A),    # full-width Latin small letters
    (0xFF66, 0xFF9F),    # half-width katakana
)

#: CJK punctuation: the CJK Symbols and Punctuation block minus the letter-like marks
#: above, the full-width ASCII punctuation, and the vertical/compatibility/small forms.
#: These glyphs carry their own spacing, so no space is ever added next to one.
_CJK_PUNCT = (
    (0x3000, 0x3004),    # ideographic space, 、 。 〃 〄
    (0x3008, 0x3020),    # 〈〉《》「」『』【】〔〕〖〗〘〙〚〛〜〝〞〟〠
    (0x3030, 0x3030),
    (0x303D, 0x303F),
    (0xFE10, 0xFE1F),    # vertical forms
    (0xFE30, 0xFE4F),    # CJK compatibility forms
    (0xFE50, 0xFE6F),    # small form variants
    (0xFF01, 0xFF0F),    # ！＂＃＄％＆＇（）＊＋，－．／
    (0xFF1A, 0xFF20),    # ：；＜＝＞？＠
    (0xFF3B, 0xFF40),    # ［＼］＾＿｀
    (0xFF5B, 0xFF65),    # ｛｜｝～ ｟｠｡｢｣､･
)

#: General punctuation shared with English (dashes, curly quotes, ellipsis). Next to an
#: unspaced letter it takes no space -- ``他说“你好”`` -- but next to a Latin word it
#: keeps whatever the English code did.
_GENERAL_PUNCT = ((0x2010, 0x205E),)

#: ASCII marks that close a clause: never preceded by a space after an unspaced letter.
_ASCII_CLOSERS = frozenset(".,!?;:)]}%")

#: Opening marks: a line may not *end* on one, so they stick to what follows.
_OPENERS = frozenset("（［｛〈《「『【〔〖〘〚〝“‘([{")


def _in(cp: int, ranges: Sequence[tuple[int, int]]) -> bool:
    return any(lo <= cp <= hi for lo, hi in ranges)


def is_han(ch: str) -> bool:
    """True for a Han ideograph (any plane)."""
    return bool(ch) and _in(ord(ch[0]), _HAN)


def is_unspaced_letter(ch: str) -> bool:
    """True for a letter of a script written without spaces between words."""
    if not ch:
        return False
    cp = ord(ch[0])
    return _in(cp, _HAN) or _in(cp, _UNSPACED_OTHER)


def is_cjk_punct(ch: str) -> bool:
    """True for CJK / full-width punctuation (which carries its own spacing)."""
    return bool(ch) and _in(ord(ch[0]), _CJK_PUNCT)


def is_cjk(ch: str) -> bool:
    """True for an unspaced letter or CJK punctuation."""
    return is_unspaced_letter(ch) or is_cjk_punct(ch)


def contains_cjk(text: str) -> bool:
    """True when *text* holds at least one CJK character. The fast path for English."""
    return any(is_cjk(ch) for ch in text or "")


def _is_general_punct(ch: str) -> bool:
    return bool(ch) and _in(ord(ch[0]), _GENERAL_PUNCT)


# --- seams --------------------------------------------------------------------------


def needs_space(left: str, right: str) -> bool:
    """Whether one space belongs between *left* and *right*, joined at a bare seam.

    ``True`` whenever neither side of the seam is CJK -- the answer ``" ".join`` always
    gave. A space is withheld only when:

    * either side of the seam is CJK punctuation (``，`` ``。`` ``「`` …), which already
      carries its own spacing;
    * both sides are unspaced letters (``世界`` + ``今天``);
    * an unspaced letter meets general punctuation such as a curly quote or ``…``, or an
      ASCII closer such as ``.`` follows one.

    A Han--Latin or Han--digit seam keeps its space (``测试 YazSes``): that is the common
    convention for mixed text, and it is what the whitespace code did, so it is the
    conservative choice where conventions differ.
    """
    if not left or not right:
        return False
    a, b = left[-1], right[0]
    if is_cjk_punct(a) or is_cjk_punct(b):
        return False
    a_letter, b_letter = is_unspaced_letter(a), is_unspaced_letter(b)
    if a_letter and (b_letter or _is_general_punct(b) or b in _ASCII_CLOSERS):
        return False
    if b_letter and _is_general_punct(a):
        return False
    return True


def join_pieces(pieces: Iterable[str]) -> str:
    """``" ".join(pieces)``, except at a seam where :func:`needs_space` says no.

    When no piece holds CJK the result **is** ``" ".join(pieces)`` -- computed by that
    very expression, empty pieces and all -- so an English caller cannot observe the
    change. With CJK present, empty pieces are skipped (an empty segment must not
    become a double space between two Han clauses).
    """
    items = list(pieces)
    if not any(contains_cjk(p) for p in items):
        return " ".join(items)
    out = ""
    for piece in items:
        if not piece:
            continue
        if out and needs_space(out, piece):
            out += " "
        out += piece
    return out


def display_width(text: str) -> int:
    """Columns *text* occupies in a caption: a CJK character counts as two.

    Han, kana and full-width punctuation are East Asian Width *Wide* or *Fullwidth*,
    rendered two columns wide in a monospaced or caption font. Every other character
    counts one, exactly as ``len`` did, so Latin, Persian and emoji widths are unchanged.
    """
    return len(text) + sum(1 for ch in text if is_cjk(ch))


# --- line-break units ---------------------------------------------------------------


def _attaches_backward(ch: str) -> bool:
    """A character that may not begin a line: closing punctuation of either kind."""
    if ch in _OPENERS:
        return False
    return is_cjk_punct(ch) or _is_general_punct(ch) or ch in _ASCII_CLOSERS


def _split_word(word: str) -> list[str]:
    """Break one whitespace-free run into atoms a line may be broken between.

    Each unspaced letter is its own atom; a Latin word or number stays whole; closing
    punctuation sticks to what precedes it and opening punctuation to what follows, so
    no line starts with ``，`` or ends with ``「`` (the basic line-breaking rule for
    Chinese and Japanese, *kinsoku shori*).
    """
    atoms: list[str] = []
    pending_open = ""
    for ch in word:
        if ch in _OPENERS:
            pending_open += ch
            continue
        if pending_open:
            atoms.append(pending_open + ch)
            pending_open = ""
            continue
        if not atoms:
            atoms.append(ch)
        elif _attaches_backward(ch):
            atoms[-1] += ch
        elif is_unspaced_letter(ch):
            atoms.append(ch)
        else:
            last = atoms[-1][-1]
            if is_unspaced_letter(last) or is_cjk_punct(last) or _is_general_punct(last):
                atoms.append(ch)
            else:
                atoms[-1] += ch
    if pending_open:
        if atoms:
            atoms[-1] += pending_open
        else:
            atoms.append(pending_open)
    return atoms


def break_units(text: str) -> list[tuple[str, str]]:
    """``(separator, unit)`` pairs a line may be broken between, in order.

    ``separator`` is what joins the unit to the one before it on the same line: ``" "``
    where the text had whitespace, ``""`` inside an unspaced run. Rebuilding the line
    is ``"".join(sep + unit …)`` with the first separator dropped; breaking a line in
    front of a unit drops that unit's separator.

    Text with no CJK yields one unit per whitespace-separated word, i.e. exactly
    ``text.split()``.
    """
    words = (text or "").split()
    if not contains_cjk(text or ""):
        return [(" ", w) for w in words]
    units: list[tuple[str, str]] = []
    for word in words:
        for i, atom in enumerate(_split_word(word)):
            units.append((" " if i == 0 else "", atom))
    return units


def render_units(units: Sequence[tuple[str, str]]) -> str:
    """Rebuild a line from :func:`break_units` output (first separator dropped)."""
    return "".join((sep if i else "") + unit for i, (sep, unit) in enumerate(units))


# --- recogniser word tokens -----------------------------------------------------------


def glue_word_tokens(raw_tokens: Sequence[str]) -> list[list[int]]:
    """Group a recogniser's raw word tokens; returns lists of token indices. Pure.

    For Chinese, Japanese, Thai, Lao and Burmese, faster-whisper does not split its
    output on spaces: it cuts wherever the tokens decode to whole code points
    (``Tokenizer.split_to_word_tokens``), so a Latin word or a number inside Mandarin
    comes back in BPE pieces -- ``" Yaz"``, ``"Ses"`` -- and once each piece is
    stripped, the fact that ``Ses`` had no space in front of it is gone. Joining the
    stripped pieces then reads ``Yaz Ses``.

    The rule uses the one signal the raw token still carries, its leading whitespace:
    a token that does **not** start with whitespace continues the previous group,
    unless both sides of the seam are unspaced letters. Two Han characters stay
    separate tokens -- each keeps its own timestamp, which diarization and captions
    need -- and :func:`needs_space` joins them without a space. Everything else that
    was written without a space is glued, so it comes back as written.

    Only meant for decodes in those languages: an English decode splits on spaces
    already, so the caller does not run this for it.
    """
    groups: list[list[int]] = []
    last_text = ""
    for i, raw in enumerate(raw_tokens):
        text = (raw or "").strip()
        if not text:
            continue
        glued_seam = bool(raw) and not raw[0].isspace()
        if (
            groups
            and glued_seam
            and not (is_unspaced_letter(last_text[-1]) and is_unspaced_letter(text[0]))
        ):
            groups[-1].append(i)
            last_text += text
        else:
            groups.append([i])
            last_text = text
    return groups


__all__ = [
    "break_units",
    "contains_cjk",
    "display_width",
    "glue_word_tokens",
    "is_cjk",
    "is_cjk_punct",
    "is_han",
    "is_unspaced_letter",
    "join_pieces",
    "needs_space",
    "render_units",
]
