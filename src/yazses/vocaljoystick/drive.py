"""From analysis frames to pointer intent, with the misfire guards (pure) — ADR-v2-095.

``formants.VocalFrameTracker`` turns audio into one :class:`~yazses.vocaljoystick.formants.VocalFrame`
per 10 ms hop and ``control.VocalJoystick`` turns a frame into a ``move``/``click``/``idle``
event. Fed straight to a pointer, that pair moves the cursor on every voiced 10 ms of anything
the microphone hears and clicks on every pitch-tracker octave error. This module is what stands
between them and the pointer, and every rule in it is a *specific, checkable* signal rather than
a heuristic (AGENTS.md rule 9, ADR-021):

* **Motion needs a sustained vowel.** A direction must hold for ``sustain_frames`` consecutive
  frames (150 ms by default) before the pointer moves, and motion stops on the first frame that
  disagrees. Running speech changes vowel quality every 50-150 ms, so most of a conversation
  never reaches the threshold; a held "eee" does on its 15th frame.
* **Motion needs some loudness.** A frame quieter than ``min_loudness`` (0.25 of the
  ``formants.loudness`` scale, about -50 dBFS) is treated as no direction, so a distant voice
  does not steer.
* **A click needs a held vowel, then a held high pitch.** ``VocalJoystick`` reports a click on
  the frame its pitch jumps; here that only *arms* a click, and only after at least
  ``sustain_frames`` voiced, loud frames. The click fires once the pitch has stayed at or above
  ``click_pitch`` for ``click_hold_frames`` more frames (50 ms). A YIN octave error lasts a frame
  or two and is dropped. The pointer is held still while a click is pending, so the click lands
  where the user was.
* **Clicks are spaced.** At most one per ``click_refractory_frames`` (0.5 s).

**Tuned on synthetic signals only.** The defaults were chosen against the synthetic
source-filter vowels in ``tests/synthetic_voice.py`` (Peterson & Barney 1952 male formants);
no real recording, no high voice and no noisy room has been measured. They are conservative on
purpose: a guard that fires too rarely costs a slower cursor, one that fires too often moves
the pointer while the user is talking.
"""
from __future__ import annotations

from dataclasses import dataclass

from yazses.vocaljoystick.control import VocalJoystick
from yazses.vocaljoystick.formants import VocalFrame

__all__ = [
    "CLICK_HOLD_FRAMES",
    "CLICK_REFRACTORY_FRAMES",
    "MIN_LOUDNESS",
    "SUSTAIN_FRAMES",
    "VOICING_GAP_FRAMES",
    "PointerIntent",
    "SustainedVowelDriver",
]

#: Frames (10 ms each) a direction must hold before the pointer moves.
SUSTAIN_FRAMES = 15
#: Below this ``formants.loudness`` value a frame steers nothing.
MIN_LOUDNESS = 0.25
#: Frames the pitch must stay at or above ``click_pitch`` after the jump before a click fires.
CLICK_HOLD_FRAMES = 5
#: Unvoiced frames a held voice may contain and still count as held (``VocalJoystick``'s gap).
VOICING_GAP_FRAMES = 5
#: Minimum frames between two clicks.
CLICK_REFRACTORY_FRAMES = 50


@dataclass(frozen=True)
class PointerIntent:
    """What the pointer should do for one frame: ``kind`` is ``move`` or ``click``."""

    kind: str
    dx: float = 0.0
    dy: float = 0.0


class SustainedVowelDriver:
    """Frames in, guarded pointer intent out. Pure state, no clock, no thread."""

    def __init__(
        self,
        joystick: VocalJoystick,
        *,
        click_pitch: float = 250.0,
        sustain_frames: int = SUSTAIN_FRAMES,
        min_loudness: float = MIN_LOUDNESS,
        click_hold_frames: int = CLICK_HOLD_FRAMES,
        click_refractory_frames: int = CLICK_REFRACTORY_FRAMES,
        clicks: bool = True,
    ) -> None:
        self._joystick = joystick
        self._click_pitch = float(click_pitch)
        self._sustain = max(1, int(sustain_frames))
        self._min_loudness = float(min_loudness)
        self._click_hold = max(1, int(click_hold_frames))
        self._refractory = max(0, int(click_refractory_frames))
        self._clicks = bool(clicks)
        self.reset()

    def reset(self) -> None:
        """Forget every run and any pending click (pause, resume, a dropped chunk)."""
        self._dir: str | None = None
        self._run = 0
        self._voiced_run = 0
        self._gap = 0
        self._pending: int | None = None
        self._since_click = self._refractory

    @property
    def engaged(self) -> bool:
        """True while a sound is held (a directed run, a voiced run) or a click is pending.

        The device monitor reads it so a re-scan never cuts into a vowel the user is
        steering with. Silence clears it within ``VOICING_GAP_FRAMES`` frames.
        """
        return self._run > 0 or self._voiced_run > 0 or self._pending is not None

    def feed(self, frame: VocalFrame) -> PointerIntent | None:
        """Consume one frame; return the pointer intent for it, or ``None`` for nothing."""
        loud = frame.loudness >= self._min_loudness
        direction = frame.direction if loud else None
        pitch = frame.pitch_hz if loud else 0.0
        if direction is not None and direction == self._dir:
            self._run += 1
        else:
            self._dir = direction
            self._run = 1 if direction is not None else 0
        held_before = self._voiced_run
        if frame.voiced and loud:
            self._voiced_run += 1
            self._gap = 0
        else:
            # A pitch tracker drops a frame or two across a sharp step (the same tolerance
            # ``VocalJoystick`` grants its click); a longer gap ends the held voice.
            self._gap += 1
            if self._gap > VOICING_GAP_FRAMES:
                self._voiced_run = 0
        self._since_click += 1
        event = self._joystick.feed(direction, frame.loudness, pitch)

        if self._pending is not None:
            if pitch >= self._click_pitch:
                self._pending += 1
                if self._pending >= self._click_hold:
                    self._pending = None
                    self._since_click = 0
                    return PointerIntent("click")
                return None  # hold the pointer still while the click is confirmed
            self._pending = None  # the high pitch did not hold: an octave error, not a click
        if event.kind == "click":
            if (self._clicks and held_before >= self._sustain
                    and self._since_click >= self._refractory):
                self._pending = 1
                if self._pending >= self._click_hold:
                    self._pending = None
                    self._since_click = 0
                    return PointerIntent("click")
            return None
        if event.kind == "move" and self._run >= self._sustain:
            return PointerIntent("move", event.dx, event.dy)
        return None
