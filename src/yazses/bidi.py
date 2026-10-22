"""Display-only bidi isolation for user text inside English UI sentences (FA-07, #516).

YazSes' chrome is English, so every message that quotes something the user said,
typed or named -- a bookmark label, a window name, a filter query, a microphone the
OS calls ``میکروفون`` -- embeds a possibly right-to-left run in a left-to-right
sentence. The Unicode bidi algorithm then resolves the *neutrals at the seam* (a
trailing ``!``, ``.``, ``:`` or quote) by the English sentence rather than by the
quoted run, and the punctuation lands on the wrong side of the Persian word:
``Bookmarked 'سلام!'.`` shows the ``!`` to the right of ``سلام``, which an RTL reader
sees as the *start* of the word. Measured in Qt 6 (``QTextLayout``, offscreen) by
``tests/test_settingsui_bidi_render.py``.

The fix the Unicode standard recommends (UAX #9, "Explicit Directional Isolates"; W3C
"Inline markup and bidirectional text in HTML") is a first-strong isolate: ``FSI text PDI``. The quoted
run then takes its direction from its own first strong letter and cannot reorder
the sentence around it. This module decides when that is needed and builds the
wrapped string. Rules (``design/specs/persian-text-and-rtl.md`` §6 and §11):

* **Never reverse a string.** Nothing here reorders code points; layout is left to
  the toolkit's bidi implementation.
* **Only when needed.** Text with no right-to-left character (bidi class ``R``,
  ``AL`` or ``AN``) gets no isolate, so every English, ASCII, URL, path and
  digits-only message stays byte-for-byte what it was (unless it carried an
  explicit bidi control, which is dropped -- see *Contained*).
* **Display copies only.** The result goes to a notification, a tooltip, a combo
  box label or a status line. It must never reach the injector, the clipboard, a
  config write or a file: ``tests/test_bidi.py`` holds that no module on those
  paths imports this one, and the call sites keep the raw value for storage.
* **Contained.** Explicit embedding, override and isolate controls inside the
  quoted text are dropped from the display copy first. A stray ``PDI`` would
  otherwise close our isolate early, and an ``RLO`` could make a quoted name render
  as its mirror -- the hidden-override case §6 names. ZWNJ, ZWJ and the directional
  marks (LRM/RLM/ALM) are ordinary characters and survive.
* **Per paragraph.** A paragraph separator ends every isolate (UAX #9 rule P1), so
  multi-line text is isolated line by line.

Pure and stdlib-only; no Qt. Used by ``tray/menu.py`` (tooltip), ``settingsui``
(microphone list, filter and save messages), ``bookmarks/service.py`` and the
daemon's window-focus toast.
"""

from __future__ import annotations

import re
import unicodedata

#: U+2068 FIRST STRONG ISOLATE: the run takes the direction of its first strong letter.
FSI = "\u2068"
#: U+2069 POP DIRECTIONAL ISOLATE: closes the matching isolate initiator.
PDI = "\u2069"

#: Explicit embeddings/overrides (U+202A..U+202E) and isolates (U+2066..U+2069) --
#: the formatting characters that open or close a directional context. Removed from
#: the display copy so nothing in the quoted text can escape or break our isolate.
_EXPLICIT_CONTROLS_RE = re.compile("[\u202A-\u202E\u2066-\u2069]")

#: Bidi class ``B`` (paragraph separators): an isolate cannot span one, so text is
#: split here and each paragraph is wrapped on its own. CRLF is one separator.
_PARAGRAPH_SPLIT_RE = re.compile("(\r\n|[\n\r\x1c-\x1e\x85\u2029])")

#: The bidi classes that make an LTR sentence need isolation around a run.
_RTL_CLASSES = frozenset({"R", "AL", "AN"})


def has_rtl(text: str) -> bool:
    """True when *text* holds a right-to-left character (bidi class R, AL or AN)."""
    return any(unicodedata.bidirectional(ch) in _RTL_CLASSES for ch in text)


def strip_explicit_controls(text: str) -> str:
    """Remove embedding, override and isolate controls; keep ZWNJ/ZWJ and marks."""
    return _EXPLICIT_CONTROLS_RE.sub("", text)


def _wrap_paragraph(paragraph: str) -> str:
    if not has_rtl(paragraph):
        return paragraph
    return f"{FSI}{paragraph}{PDI}"


def wrap_user_text(text: object) -> str:
    """The display copy of *text*, isolated with FSI..PDI only where it needs it.

    Returns *text* unchanged when it has no right-to-left character and no explicit
    bidi control. Otherwise the controls are dropped and every paragraph that holds
    a right-to-left character is wrapped. Never raises on a ``str``; a non-string is
    formatted with ``str()`` first so a caller can pass a config value as it is.
    """
    raw = text if isinstance(text, str) else str(text)
    if not raw:
        return raw
    cleaned = strip_explicit_controls(raw)
    if not has_rtl(cleaned):
        return cleaned
    parts = _PARAGRAPH_SPLIT_RE.split(cleaned)
    # re.split with a capturing group alternates paragraph, separator, paragraph...
    return "".join(
        part if index % 2 else _wrap_paragraph(part) for index, part in enumerate(parts)
    )


def quote_user_text(text: object) -> str:
    """A quoted value for a message: ``repr`` for English, ``'FSI…PDI'`` for RTL text.

    For the call sites that showed a value with ``!r``. A value with no
    right-to-left character and no bidi control reads exactly as before. A Persian
    one is quoted by hand instead, for two reasons: ``repr`` escapes ZWNJ -- an
    ordinary letter of Persian orthography (``می<ZWNJ>کنم``) -- as a literal ``\\u200c``,
    and the quotes belong to the English sentence, so they sit *outside* the isolate
    where they resolve left-to-right with it (W3C, "Inline markup and bidirectional
    text in HTML": keep the surrounding sentence's punctuation outside the isolate).
    """
    if not isinstance(text, str):
        return repr(text)
    if not has_rtl(text) and not _EXPLICIT_CONTROLS_RE.search(text):
        return repr(text)
    return f"'{wrap_user_text(text)}'"
