"""The audible stand-in for the scan strip (`yazses.mouthswitch.announce`) — fakes only.

Where the overlay cannot draw the highlight, each step is announced: an earcon cue at once
and the item's name in the offline voice. These pin the parts a user who cannot see the
screen depends on:

* the estimate the scanner lengthens a step by is total and grows with the label;
* each announce plays the right cue and says the label, and a scan that stops cuts the
  voice -- but never cancels a voice it is not using (that would cut someone's read-back);
* a new step cuts a name still being said instead of queueing behind it;
* nothing raises into the audio worker, whatever the cue or the voice does.
"""
from __future__ import annotations

import math
import threading
import time

import pytest

from yazses.mouthswitch.announce import (
    FIRST_CUE,
    SPEECH_LEAD_S,
    STEP_CUE,
    ScanAnnouncer,
    speech_duration_s,
)
from yazses.mouthswitch.scanner import ScanItem

ENTER = ScanItem("enter", "command")
SCROLL_DOWN = ScanItem("scroll down", "pointer", op="scroll", dy=3)


class FakeVoice:
    """Records what it was asked to say, and every claim and cancel, in order."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def speak(self, text: str) -> None:
        self.events.append(("speak", text))

    def cancel(self) -> None:
        self.events.append(("cancel", ""))

    def begin(self) -> None:
        self.events.append(("begin", ""))

    @property
    def said(self) -> list[str]:
        return [text for kind, text in self.events if kind == "speak"]

    @property
    def cancels(self) -> int:
        return sum(1 for kind, _ in self.events if kind == "cancel")


def _inline(voice: FakeVoice | None = None, cues: list[str] | None = None) -> ScanAnnouncer:
    return ScanAnnouncer(
        cue=cues.append if cues is not None else None,
        speak=voice.speak if voice else None,
        cancel=voice.cancel if voice else None,
        begin=voice.begin if voice else None,
        thread=False,
    )


# ---- the estimate ----------------------------------------------------------------------------


def test_the_estimate_grows_with_the_label_and_starts_after_the_lead():
    short, long = speech_duration_s("undo"), speech_duration_s("scroll down")
    assert SPEECH_LEAD_S < short < long


def test_the_estimate_is_whitespace_blind():
    assert speech_duration_s("  scroll \t down ") == speech_duration_s("scroll down")


@pytest.mark.parametrize("text", ["", "   ", None, 7])
def test_nothing_to_say_takes_no_time(text):
    assert speech_duration_s(text) == 0.0


def test_a_faster_voice_takes_less_time_and_the_speed_is_clamped():
    assert speech_duration_s("scroll down", 2.0) < speech_duration_s("scroll down", 1.0)
    assert speech_duration_s("scroll down", 50.0) == speech_duration_s("scroll down", 2.0)
    assert speech_duration_s("scroll down", 0.01) == speech_duration_s("scroll down", 0.5)


@pytest.mark.parametrize("speed", ["fast", None, float("nan"), float("inf"), -1.0, 0.0])
def test_an_unusable_speed_reads_as_normal(speed):
    value = speech_duration_s("enter", speed)
    assert math.isfinite(value) and value == speech_duration_s("enter", 1.0)


# ---- what an announcer can do ----------------------------------------------------------------


def test_modes_follow_the_outputs_it_was_given():
    assert _inline(FakeVoice(), []).mode == "speech"
    assert _inline(None, []).mode == "earcon"
    assert _inline(FakeVoice(), None).mode == "speech"
    nothing = _inline(None, None)
    assert nothing.mode == "" and nothing.can_announce is False


def test_without_a_voice_an_announcement_takes_no_time():
    assert _inline(None, []).announcement_s(SCROLL_DOWN) == 0.0
    assert _inline(FakeVoice(), []).announcement_s(SCROLL_DOWN) == speech_duration_s(
        "scroll down")


def test_an_estimate_that_raises_reads_as_no_time():
    def boom(text):
        raise RuntimeError("estimate failed")

    announcer = ScanAnnouncer(speak=lambda text: None, duration_s=boom, thread=False)
    assert announcer.announcement_s(ENTER) == 0.0


# ---- announcing ------------------------------------------------------------------------------


def test_each_step_plays_its_cue_and_says_the_label():
    voice, cues = FakeVoice(), []
    announcer = _inline(voice, cues)
    announcer.announce(ENTER, first=True)
    announcer.announce(SCROLL_DOWN, first=False)
    assert cues == [FIRST_CUE, STEP_CUE]
    assert voice.said == ["enter", "scroll down"]
    # The voice is claimed before each name, so a stop after the claim is never lost.
    assert voice.events[:2] == [("begin", ""), ("speak", "enter")]


def test_cues_only_says_nothing_and_still_counts_steps():
    cues: list[str] = []
    announcer = _inline(None, cues)
    for first in (True, False, False, True):
        announcer.announce(ENTER, first=first)
    assert cues == [FIRST_CUE, STEP_CUE, STEP_CUE, FIRST_CUE]


def test_a_stop_with_nothing_being_said_cancels_nothing():
    """The voice is shared with read-back: an idle stop must not cut someone else's speech."""
    voice = FakeVoice()
    announcer = _inline(voice, [])
    announcer.announce(ENTER, first=True)  # said and finished, inline
    announcer.stop()
    announcer.stop()
    assert voice.cancels == 0


def test_a_broken_cue_or_voice_never_raises_into_the_worker():
    def boom(*_args):
        raise OSError("no audio device")

    announcer = ScanAnnouncer(cue=boom, speak=boom, cancel=boom, begin=boom, thread=False)
    announcer.announce(ENTER, first=True)
    announcer.stop()
    announcer.close()


def test_after_close_nothing_is_announced():
    voice, cues = FakeVoice(), []
    announcer = _inline(voice, cues)
    announcer.close()
    announcer.announce(ENTER, first=True)
    assert cues == [] and voice.said == []


# ---- the speech thread -----------------------------------------------------------------------


class BlockingVoice(FakeVoice):
    """``speak`` holds until cancelled (or released), like a real voice mid-word."""

    def __init__(self) -> None:
        super().__init__()
        self.speaking = threading.Event()
        self.release = threading.Event()

    def speak(self, text: str) -> None:
        self.events.append(("speak", text))
        self.speaking.set()
        self.release.wait(timeout=2.0)
        self.speaking.clear()

    def cancel(self) -> None:
        self.events.append(("cancel", ""))
        self.release.set()

    def begin(self) -> None:
        self.events.append(("begin", ""))
        self.release.clear()


def _threaded(voice: FakeVoice) -> ScanAnnouncer:
    return ScanAnnouncer(speak=voice.speak, cancel=voice.cancel, begin=voice.begin)


def _wait_for(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        threading.Event().wait(0.005)
    return predicate()


def test_announce_returns_at_once_and_the_name_is_said_on_its_own_thread():
    voice = BlockingVoice()
    announcer = _threaded(voice)
    announcer.announce(ENTER, first=True)  # returns while the voice is still speaking
    assert voice.speaking.wait(timeout=2.0)
    assert voice.said == ["enter"]
    announcer.close()


def test_a_new_step_cuts_the_name_still_being_said():
    voice = BlockingVoice()
    announcer = _threaded(voice)
    announcer.announce(ENTER, first=True)
    assert voice.speaking.wait(timeout=2.0)
    announcer.announce(SCROLL_DOWN, first=False)
    assert _wait_for(lambda: voice.said == ["enter", "scroll down"])
    # The cut came before the next name claimed the voice.
    kinds = [kind for kind, _ in voice.events]
    assert kinds.index("cancel") < len(kinds) - 1 - kinds[::-1].index("begin")
    announcer.close()


def test_a_stop_cuts_the_name_being_said_and_close_ends_the_thread():
    voice = BlockingVoice()
    announcer = _threaded(voice)
    announcer.announce(ENTER, first=True)
    assert voice.speaking.wait(timeout=2.0)
    announcer.stop()
    assert voice.cancels == 1
    announcer.close()
    assert announcer._worker is None


def test_the_step_cues_are_their_own_short_motifs_not_the_idle_fallback():
    """`earcon_for` answers an unknown event with the idle tone; these must be known."""
    from yazses.earcon.tones import earcon_for

    step, first = earcon_for(STEP_CUE), earcon_for(FIRST_CUE)
    assert step != earcon_for("idle") and first != earcon_for("idle")
    assert step != first  # the first item sounds different, so the steps can be counted
    assert all(tone.dur_ms <= 60 for tone in step + first)
