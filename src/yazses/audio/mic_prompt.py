"""A spoken answer to the mic-change guard's question.

The mic-change guard is the one part of the pipeline that *asks* rather than tells:
when capture moves to another device, or a run of clips comes back silent, it pops
a toast offering **Re-calibrate**, **Pin this mic** and **Ignore**. Those are
buttons, and only buttons — so the daemon interrupts you with a question that can
only be answered with a pointer, in an application whose reason to exist is that
some people cannot use one.

It is also, specifically, a question about the microphone. The person most likely
to see it is the person whose dictation has just stopped working, and telling them
to reach for the mouse is the moment the hands-free promise breaks.

Counted on 2026-08-16 (ADR-022, Spec 1) this is one of exactly **two** daemon-
initiated states with no voice-only exit. It is the half that needs no change to
the command-safety gate — its three actions are already dispatched from a string
key, and it holds nothing dangerous — which is why it can land while the other half
waits for a decision.

Two things keep it from firing when it should not, and both matter more than the
matching does:

* **The whole utterance must be the answer.** "ignore" is an ordinary English word
  and so is "pin". This is the lesson the revise grammar already learned — anchor
  at both ends or a suffix match swallows "click undo" instead of typing it.
* **The question must still be open.** An answer only counts inside a window after
  the toast. Without one, a prompt from three hours ago quietly re-arms the word
  "ignore" for the rest of the session.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Keys are exactly what ``daemon._on_mic_action`` already dispatches on, so the
#: spoken route and the clicked route cannot drift apart -- there is one handler.
ANSWERS: dict[str, tuple[str, ...]] = {
    "recalibrate": (
        "recalibrate",
        "re calibrate",
        "recalibrate the mic",
        "recalibrate the microphone",
        "calibrate the mic",
        "calibrate the microphone",
    ),
    "pin": (
        "pin this mic",
        "pin this microphone",
        "pin the mic",
        "pin the microphone",
        "pin this one",
    ),
    "ignore": (
        "ignore",
        "ignore it",
        "ignore that",
        "dismiss",
        "never mind",
        "nevermind",
    ),
}

#: How long the toast's question stays answerable by voice. Long enough to notice a
#: toast, read three options and hold a key; short enough that the word "ignore"
#: is not a live control word for the rest of the session.
DEFAULT_WINDOW_S = 45.0

_STRIP = re.compile(r"[^\w\s]+")
_SPACES = re.compile(r"\s+")


def _normalize(text: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace.

    Whisper punctuates freely -- "Ignore." and "ignore" are the same answer, and a
    trailing full stop is not a reason to type the word into the user's document.
    """
    return _SPACES.sub(" ", _STRIP.sub(" ", (text or "").lower())).strip()


def match_mic_answer(text: str) -> str | None:
    """Which button this utterance is, or ``None`` if it is ordinary dictation.

    Matches the *entire* utterance only. "Please ignore the second paragraph" is
    prose and must be typed; a suffix or substring match would eat it.
    """
    spoken = _normalize(text)
    if not spoken:
        return None
    for key, phrases in ANSWERS.items():
        if spoken in phrases:
            return key
    return None


@dataclass
class MicPrompt:
    """When the guard last asked, so an answer can be scoped to the question.

    Deliberately not a queue and not a count: the toast is replaced rather than
    stacked, so there is only ever one open question and the latest one wins.
    """

    asked_at: float | None = None

    def ask(self, now: float) -> None:
        self.asked_at = now

    def close(self) -> None:
        self.asked_at = None

    def is_open(self, now: float, window_s: float) -> bool:
        if self.asked_at is None:
            return False
        if window_s <= 0:
            return False
        elapsed = now - self.asked_at
        # A negative elapsed means the clock moved backwards; treat the question as
        # open rather than stuck-shut, since the alternative strands the user with a
        # prompt they cannot answer at all.
        return elapsed <= window_s
