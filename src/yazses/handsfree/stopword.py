"""The voice stop word: say a short phrase, hands-free input pauses (pure).

A person who cannot reach a keyboard or aim a pointer still has a voice. When the Head-Pointer
runs away, the way to stop it must not need the thing that has run away. `yazses handsfree
pause` is the terminal path, the panel's Pause button needs a pointer, and the chord needs the
camera; this is the fourth: a spoken phrase.

**What it decides, and nothing else.** Given one transcribed utterance and the configured
phrase, :func:`matches` says whether the utterance *is* the stop phrase. It does not pause
anything, touch the gate, or type; the daemon does that. This module has no imports from the rest
of the package (stdlib only), so the rule that decides when a stop fires can be tested directly
with plain strings and no camera, no daemon, no audio.

**Whole utterance only.** The match is an equality test on the *entire* transcript, never a
search inside it. "Pause hands free" pauses; "I will pause hands free input while I type" is
dictation and is typed. That is the whole false-positive defence, and it is deliberately the only
one: a stop word that fires on ordinary dictation teaches people to switch it off
(AGENTS.md rule 9, ADR-021), and a switched-off stop word is the worst outcome for the one user
who needs it. The same shape as `cmdsafety/spoken.py`, for the same reason (issue #164).

**Tolerances, and only these.** Case, edge punctuation, and the way the recogniser happens to
space or hyphenate a compound: "Pause hands-free." and "pause handsfree" are the phrase
"pause hands free". Nothing fuzzy beyond that -- no edit distance, no "contains", no leading
filler -- because every tolerance widens the set of sentences that pause the user's input.

**It can only pause.** There is no resume phrase and no function here that could build one.
Resuming by voice would be a second, separate risk (a stray phrase re-arming a pointer the user
just stopped); resume is `yazses handsfree resume` or the Hands-free controls window (Settings -> Hands-free
controls); the tray menu has no hands-free item.

**The default is provisional.** No recognition-accuracy data exists for any phrase in any accent
or room (``design/eye-control/GOVERNANCE.md``). "pause hands free" is chosen because it is
unlikely to be the whole of a dictated utterance; whether Whisper reliably transcribes it is
unmeasured, which is why the config key accepts any phrase that passes :func:`problem`.
"""
from __future__ import annotations

import re
import unicodedata

__all__ = [
    "DEFAULT_STOP_PHRASE",
    "MAX_WORDS",
    "MIN_WORDS",
    "matches",
    "normalise",
    "problem",
]

#: PROVISIONAL. What `[handsfree] enabled = true` puts in ``[handsfree_safety] stop_phrase``.
DEFAULT_STOP_PHRASE = "pause hands free"

#: A one-word stop phrase ("stop", "pause") is a whole utterance of ordinary dictation far too
#: often: a person dictating a list says exactly that word. Two words is the floor.
MIN_WORDS = 2
#: A long phrase is not a stop word: it is hard to say, and hard to have recognised exactly.
MAX_WORDS = 6

_EDGE_NOISE = re.compile(r"^[^\w]+|[^\w]+$", re.UNICODE)
_WORD_SPLIT = re.compile(r"[\s\-‐-―]+")
_NOT_ALNUM = re.compile(r"[\W_]+", re.UNICODE)


def normalise(text: str) -> str:
    """Reduce an utterance to the form it is compared in. Pure.

    NFKC + case-fold (a curly apostrophe or full-width form cannot make a phrase miss), edge
    punctuation removed, hyphens read as spaces, and runs of whitespace collapsed.
    """
    folded = unicodedata.normalize("NFKC", text or "").casefold()
    stripped = _EDGE_NOISE.sub("", folded)
    return " ".join(w for w in _WORD_SPLIT.split(stripped) if w)


def _key(text: str) -> str:
    """The comparison key: the letters and digits of the normalised text, nothing between them.

    Dropping the *interior* boundaries is what lets "hands free", "hands-free" and "handsfree"
    be one phrase without a variant table. It is still an equality test on the whole utterance,
    so it cannot make a longer sentence match.
    """
    return _NOT_ALNUM.sub("", normalise(text))


def problem(phrase: object) -> str | None:
    """Why ``phrase`` is not usable as a stop phrase, or None if it is. Pure.

    The empty string is valid: it means the stop word is off.
    """
    if not isinstance(phrase, str):
        return "must be text"
    if not phrase.strip():
        return None
    words = normalise(phrase).split()
    if not _key(phrase):
        return "has no letters or digits to say"
    if len(words) < MIN_WORDS:
        return (
            f"is a single word; use at least {MIN_WORDS} words, because one word is too often "
            "the whole of a dictated utterance"
        )
    if len(words) > MAX_WORDS:
        return f"is {len(words)} words; keep it to {MAX_WORDS} or fewer so it is easy to say and to hear"
    return None


def matches(utterance: str, phrase: str) -> bool:
    """Is this utterance, in full, the stop phrase? False when the stop word is off or invalid.

    ``phrase`` empty (off) or failing :func:`problem` never matches: an unusable phrase must not
    become a different, looser one.
    """
    if not isinstance(phrase, str) or not phrase.strip() or problem(phrase) is not None:
        return False
    spoken = _key(utterance)
    return bool(spoken) and spoken == _key(phrase)
