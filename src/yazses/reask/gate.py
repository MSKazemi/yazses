"""The re-ask hold: park one burst, let a spoken pick patch the uncertain word (ADR-v2-077).

`confidence.py` answers three small questions (which tokens are uncertain, what are the
confusable alternatives, which option did the user pick). This module answers the one the
daemon actually has: **given a finished burst and its per-word probabilities, do I hold it
and ask, and what do I do with the next thing the user says?**

It is dependency-free apart from the standard library. The one side effect it owns — a
timer that releases an unanswered hold — is injected (`timer_factory`), so every branch is
testable without sleeping.

Design rules, all from ADR-021 ("a guard is judged on how rarely it fires"):

* **Hold only on a specific, checkable signal.** The uncertain word must be in the curated
  confusion table, must be the *only* uncertain confusable word in the burst, and must
  appear exactly once in the text that is about to be typed (so the patch is unambiguous).
  Anything else types with no comment.
* **A reply is a tiny anchored grammar, not a search.** ``parse_choice`` finds "one" or
  "there" anywhere in a sentence; applied to the user's *next dictation* that would swallow
  "I want one coffee". `reply_choice` accepts a reply only if the whole utterance is an
  ordinal or one of the options.
* **Nothing is lost.** A reply that is not a pick releases the held text and then types the
  reply as ordinary dictation; a hold nobody answers is released by the timer.
* **Metadata only.** The gate never logs or stores the transcript.
"""
from __future__ import annotations

import math
import re
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from yazses.reask.confidence import confusion_set, low_confidence_spans

#: How long an unanswered hold waits before it is released. Long enough to say one word,
#: short enough that the user's text does not feel lost.
HOLD_SECONDS = 10.0

#: Below this a word's probability is treated as "the backend did not report one" rather
#: than "certainly wrong". `Word.probability` defaults to 0.0, and an engine that has no
#: per-word probabilities would otherwise make *every* confusable word look uncertain.
_MIN_REPORTED_PROBABILITY = 1e-6

_ORDINALS = {"first": 0, "second": 1, "third": 2, "1": 0, "2": 1, "3": 2}
_NUMBER_WORDS = {"one": 0, "two": 1, "three": 2}
_FILLER = r"(?:(?:the|a)\s+)?"
# Anchored at both ends (`fullmatch`): "the second one", "second", "option 2", "number three".
_ORDINAL_REPLY = re.compile(
    rf"{_FILLER}(first|second|third)(?:\s+(?:one|option|choice))?"
    r"|(?:option|number|choice)\s+(first|second|third|one|two|three|1|2|3)"
)
_NON_WORD = re.compile(r"[^a-z0-9' ]")


def _norm(text: str) -> str:
    """Lowercase, drop punctuation, collapse spaces. ``’`` is treated as ``'``."""
    t = (text or "").lower().replace("’", "'")
    return " ".join(_NON_WORD.sub(" ", t).split())


def reply_choice(reply: str, options: Sequence[str]) -> str | None:
    """Resolve a spoken reply to one of *options*, or ``None``. Pure.

    The whole utterance must be the pick: an ordinal ("second", "the third one", "option
    2") or exactly one of the options ("there"). A bare number word is deliberately **not**
    an ordinal here — ``two`` is itself an option for ``to/too/two``.
    """
    t = _norm(reply)
    if not t or not options:
        return None
    # An option spoken as itself wins, so "two" picks the word "two".
    for opt in options:
        if t == _norm(opt):
            return opt
    m = _ORDINAL_REPLY.fullmatch(t)
    if m is None:
        return None
    key = next(g for g in m.groups() if g)
    idx = _ORDINALS.get(key, _NUMBER_WORDS.get(key))
    if idx is None or idx >= len(options):
        return None
    return options[idx]


def _bare(word: str) -> str:
    return re.sub(r"[^a-z']", "", (word or "").lower().replace("’", "'"))


def _word_pattern(bare: str) -> re.Pattern[str]:
    body = "".join("['’]?" if ch == "'" else re.escape(ch) for ch in bare)
    return re.compile(rf"(?<![A-Za-z'’]){body}(?![A-Za-z'’])", re.IGNORECASE)


def find_uncertain_word(
    words: Sequence[tuple[str, float]], threshold: float
) -> str | None:
    """The one uncertain, confusable word in a burst, or ``None``. Pure.

    ``words`` is ``(text, probability)``; ``threshold`` is a log-probability (the ``[reask]
    threshold`` setting). Returns ``None`` when nothing is uncertain, when the uncertain
    words are not in the confusion table, or when more than one confusable word is
    uncertain (the burst is probably just noisy — asking about each would be the
    nagging ADR-021 warns against).
    """
    toks: list[str] = []
    lps: list[float] = []
    for text, prob in words:
        toks.append(text)
        # Unreported probability reads as certain, so it can never trigger a hold.
        lps.append(
            math.log(prob) if prob > _MIN_REPORTED_PROBABILITY else 0.0
        )
    hits = [
        sp.text for sp in low_confidence_spans(toks, lps, threshold)
        if " " not in sp.text.strip() and confusion_set(sp.text)
    ]
    return _bare(hits[0]) if len(hits) == 1 else None


def locate(text: str, bare: str) -> re.Match[str] | None:
    """The single whole-word occurrence of *bare* in *text*, else ``None``. Pure."""
    found = list(_word_pattern(bare).finditer(text))
    return found[0] if len(found) == 1 else None


def patch(text: str, match: re.Match[str], choice: str) -> str:
    """Replace *match* in *text* with *choice*, keeping a leading capital. Pure."""
    old = match.group(0)
    new = choice[:1].upper() + choice[1:] if old[:1].isupper() else choice
    return text[: match.start()] + new + text[match.end():]


@dataclass(frozen=True)
class Verdict:
    """What the daemon should do with a burst.

    ``text`` is what to type now (``None`` = type nothing: it was held, or the burst was
    consumed as a pick). ``prompt`` is a one-line question to show, set only on a new hold.
    ``action`` is metadata for the event log: ``"held"``, ``"picked"``, ``"released"`` or
    ``""`` when the gate did nothing.
    """

    text: str | None
    prompt: str = ""
    action: str = ""


@dataclass
class _Hold:
    text: str
    bare: str
    options: list[str]


class ReaskGate:
    """Holds at most one burst. Thread-safe; the daemon's worker and the timer both call in."""

    def __init__(
        self,
        on_expire: Callable[[str], None],
        *,
        hold_seconds: float = HOLD_SECONDS,
        timer_factory: Callable[[float, Callable[[], None]], threading.Timer] = threading.Timer,
    ) -> None:
        self._on_expire = on_expire
        self._hold_seconds = hold_seconds
        self._timer_factory = timer_factory
        self._lock = threading.Lock()
        self._hold: _Hold | None = None
        self._timer: threading.Timer | None = None

    @property
    def pending(self) -> bool:
        with self._lock:
            return self._hold is not None

    def _take(self) -> _Hold | None:
        """Atomically remove the hold. Whoever gets it owns the text."""
        with self._lock:
            hold, self._hold = self._hold, None
            timer, self._timer = self._timer, None
        if timer is not None:
            timer.cancel()
        return hold

    def _expired(self) -> None:
        hold = self._take()
        if hold is not None:
            self._on_expire(hold.text)

    def cancel(self) -> str | None:
        """Drop the hold and return its text (for shutdown), or ``None``."""
        hold = self._take()
        return hold.text if hold is not None else None

    def handle(
        self, text: str, words: Sequence[tuple[str, float]], threshold: float
    ) -> Verdict:
        """Decide what to do with *text*, the burst about to be typed."""
        hold = self._take()
        if hold is not None:
            # This burst is the reply (or the user moved on). Either way the held text is
            # resolved now and is never dropped.
            options = hold.options
            choice = reply_choice(text, options)
            if choice is not None:
                match = locate(hold.text, hold.bare)
                if match is not None:
                    return Verdict(patch(hold.text, match, choice), action="picked")
                return Verdict(hold.text, action="released")
            sep = "" if text[:1].isspace() else " "
            return Verdict(hold.text + sep + text, action="released")

        bare = find_uncertain_word(words, threshold)
        if bare is None:
            return Verdict(text)
        match = locate(text, bare)
        options = confusion_set(bare)
        if match is None or len(options) < 2:
            return Verdict(text)
        with self._lock:
            self._hold = _Hold(text, bare, options)
            timer = self._timer_factory(self._hold_seconds, self._expired)
            timer.daemon = True
            self._timer = timer
        timer.start()
        spoken = " / ".join(options)
        ordinals = ", ".join(("first", "second", "third")[: len(options)])
        return Verdict(
            None,
            prompt=f"Not sure which word: {spoken}. Say {ordinals}, or the word itself.",
            action="held",
        )
