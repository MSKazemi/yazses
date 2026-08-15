"""Spoken confirm/cancel matching for the command safety gate (pure) — ADR-v2-065.

`classify.py` decides whether a dictated command is dangerous. This decides whether
the *next* utterance is the word that releases it.

Two rules do all the work here, and both are scars from previous wiring attempts on
this repository:

**Anchored at both ends.** `confirm` and `cancel` are ordinary English words. A
`re.search` for them would swallow "cancel the meeting" and "I can confirm that" —
dictated prose that must be typed, not treated as a control word. Issue #164 records
a merged PR where exactly this bug ate 4 of 6 test phrases, and
`commands/revise.py::_SCRATCH_RE` anchors `^…$` for the same reason. A control word
is only a control word when it is the *entire* utterance.

**Normalised before matching, not during.** By the time an utterance reaches here it
may have been through voice punctuation and ITN, so "confirm" can arrive as
"Confirm." or " confirm ". Stripping the decoration is separate from the match so
the match itself stays a plain equality test that is obvious to read and impossible
to get subtly wrong with a regex.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

# Leading/trailing punctuation and whitespace only. Interior characters are left
# alone: a phrase like "yes, run it" is a legitimate confirm phrase and its comma is
# part of what the user configured.
_EDGE_NOISE = re.compile(r"^[^\w]+|[^\w]+$", re.UNICODE)
_WHITESPACE = re.compile(r"\s+")

#: What `confirm`/`cancel` mean when the config leaves them unset. Deliberately
#: short and unambiguous: every phrase here is one a person would only say when they
#: mean it, and none is a common sentence opener.
DEFAULT_CONFIRM_WORDS = ("confirm", "confirm that", "yes run it", "run it")
DEFAULT_CANCEL_WORDS = ("cancel", "cancel that", "never mind", "forget it")


def normalise_utterance(text: str) -> str:
    """Reduce an utterance to the form control words are compared in. Pure.

    Case-folded, edge punctuation removed, interior whitespace collapsed, and
    Unicode-normalised so a curly apostrophe or a full-width form cannot make an
    otherwise-identical phrase miss.
    """
    folded = unicodedata.normalize("NFKC", text or "").casefold()
    return _WHITESPACE.sub(" ", _EDGE_NOISE.sub("", folded)).strip()


def match_control(
    text: str,
    confirm_words: Iterable[str] | str | None = None,
    cancel_words: Iterable[str] | str | None = None,
) -> str | None:
    """Return ``"confirm"``, ``"cancel"``, or ``None`` if this is ordinary dictation.

    The utterance must equal a control phrase in full. Anything longer is prose that
    happens to contain the word, and prose gets typed.

    Confirm is checked first. If a phrase is configured as both -- a misconfiguration,
    not a real case -- the safe reading is not obvious either way, so the documented
    one is that the more explicit intent wins and it is deterministic.
    """
    spoken = normalise_utterance(text)
    if not spoken:
        return None
    confirm = _phrases(confirm_words, DEFAULT_CONFIRM_WORDS)
    cancel = _phrases(cancel_words, DEFAULT_CANCEL_WORDS)
    if spoken in confirm:
        return "confirm"
    if spoken in cancel:
        return "cancel"
    return None


def _phrases(
    configured: Iterable[str] | str | None, fallback: tuple[str, ...]
) -> frozenset[str]:
    """Normalise a configured phrase list, falling back when it is empty or absent.

    An empty list falls back rather than disabling the words. Emptying
    `confirm_words` would otherwise leave a held command with **no** way to release
    it -- a config edit that silently bricks the feature, which is worse than the
    behaviour it replaced.

    A bare string is accepted as a one-phrase list. `confirm_words = "confirm"` is
    the natural thing to write in TOML and iterating it character by character would
    turn the release word into the letters "c", "o", "n" -- a silent, baffling
    failure rather than a config error.
    """
    default = frozenset(normalise_utterance(p) for p in fallback)
    if not configured:
        return default
    phrases = [configured] if isinstance(configured, str) else list(configured)
    normalised = {normalise_utterance(p) for p in phrases if normalise_utterance(p)}
    return frozenset(normalised) or default
