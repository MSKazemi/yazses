"""Hear the scan when it cannot be seen: a step cue and the item's name (ADR-v2-097).

The scan strip is drawn by the overlay, which does not run everywhere (a native Wayland
session, a base install without the ``desktop`` extra). Without it a click would select an
item nobody can see, so the switch used to refuse to start. This module lets the switch run
there *audibly* instead, with two existing outputs the daemon hands in:

* an **earcon cue** at every step (``[earcon]``, ADR-v2-096): ``scan_first`` when the scan
  is back at the first item, ``scan_step`` for every other item, so the steps can be counted;
* the item's **name, spoken** by the offline read-back voice (``[tts]``), when it can speak.

Either one is enough to run; with neither, ``build_mouthswitch`` still refuses.

**What you hear is what a click selects.** The runner announces a step the moment the pure
scanner's timeline enters it, from the same clock the select-at-onset rule reads. The scanner
holds an item lit for at least as long as its name takes to say (:func:`speech_duration_s`,
injected as ``announce_s``), so the highlight never moves on mid-word. A new step cancels an
announcement still sounding rather than queueing behind it: a late name describes an item
the scan has already left (the same reasoning as ``earcon/play.py``).

Never blocks the audio worker, never raises into it. Imports nothing heavy: the cue and the
voice are callables, so the tests run on fakes.
"""
from __future__ import annotations

import logging
import math
import threading
from collections.abc import Callable

from yazses.mouthswitch.scanner import ScanItem

__all__ = [
    "FIRST_CUE",
    "SPEECH_LEAD_S",
    "SPEECH_S_PER_CHAR",
    "STEP_CUE",
    "ScanAnnouncer",
    "speech_duration_s",
]

log = logging.getLogger(__name__)

#: Earcon events (``earcon/tones.py``): the scan is on its first item / on any other item.
FIRST_CUE = "scan_first"
STEP_CUE = "scan_step"

#: Time from "speak" to the end of the first audible sound that is not the word itself: the
#: offline voice synthesises the whole word before it plays. A provisional allowance, not a
#: measurement -- the synthesis time depends on the CPU and the voice.
SPEECH_LEAD_S = 0.35
#: Seconds per character of the label at speed 1.0 (about 160 words a minute). Provisional.
SPEECH_S_PER_CHAR = 0.075
_MIN_SPEED = 0.5
_MAX_SPEED = 2.0


def speech_duration_s(text: object, speed: object = 1.0) -> float:
    """How long the offline voice takes to say ``text``, estimated. Pure, total.

    ``0.0`` for an empty label. ``speed`` is ``[tts] speed``; anything unusable reads as
    1.0 and the rest is clamped to 0.5-2.0. An *estimate*: the scanner uses it to keep an
    item lit until its name has been said, so erring long only slows the scan.
    """
    words = " ".join(str(text).split()) if isinstance(text, str) else ""
    if not words:
        return 0.0
    try:
        rate = float(speed)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        rate = 1.0
    if not math.isfinite(rate) or rate <= 0.0:
        rate = 1.0
    rate = min(_MAX_SPEED, max(_MIN_SPEED, rate))
    return SPEECH_LEAD_S + len(words) * SPEECH_S_PER_CHAR / rate


class ScanAnnouncer:
    """Announces each scan step: a cue at once, the item's name on a speech thread.

    ``cue(event)`` plays an earcon and must not block (``EarconPlayer.play``). ``speak(text)``
    blocks until the text has been said (``TtsBackend.speak``); ``cancel()`` stops it, and
    ``begin()`` (Kokoro's, optional) claims the next utterance so a cancel issued after the
    claim is never lost. ``duration_s(text)`` is the estimate the scanner lengthens a step by.
    With ``thread=False`` the name is spoken inline -- the test path.
    """

    def __init__(
        self,
        *,
        cue: Callable[[str], None] | None = None,
        speak: Callable[[str], None] | None = None,
        cancel: Callable[[], None] | None = None,
        begin: Callable[[], None] | None = None,
        duration_s: Callable[[str], float] = speech_duration_s,
        thread: bool = True,
    ) -> None:
        self._cue = cue
        self._speak = speak
        self._cancel = cancel
        self._begin = begin
        self._duration = duration_s
        self._use_thread = thread
        self._lock = threading.Lock()
        self._wake = threading.Condition(self._lock)
        #: The name waiting to be said and the generation it belongs to.
        self._pending: tuple[str, int] | None = None
        #: Bumped by every announce and every stop; an utterance from an older one is stale.
        self._generation = 0
        #: The generation whose name is being said right now, or None.
        self._speaking: int | None = None
        self._closed = False
        self._worker: threading.Thread | None = None

    @property
    def can_announce(self) -> bool:
        """At least one of the two outputs exists."""
        return self._cue is not None or self._speak is not None

    @property
    def mode(self) -> str:
        """``"speech"`` when names are spoken, ``"earcon"`` for cues only, else ``""``."""
        if self._speak is not None:
            return "speech"
        return "earcon" if self._cue is not None else ""

    def announcement_s(self, item: ScanItem) -> float:
        """How long announcing ``item`` takes: its spoken name, or ``0.0`` without a voice."""
        if self._speak is None:
            return 0.0
        try:
            return float(self._duration(item.label))
        except Exception:
            log.debug("Mouth-Sound Switch: announcement estimate raised", exc_info=True)
            return 0.0

    def announce(self, item: ScanItem, *, first: bool) -> None:
        """A step began on ``item``. Never blocks (threaded), never raises."""
        if self._closed:
            return
        if self._cue is not None:
            try:
                self._cue(FIRST_CUE if first else STEP_CUE)
            except Exception:
                log.debug("Mouth-Sound Switch: step cue raised", exc_info=True)
        if self._speak is None:
            return
        with self._wake:
            self._generation += 1
            generation = self._generation
            if self._speaking is not None:
                # The previous name is still sounding: the scan has left that item. Cut it
                # under the lock, so the cut lands before the next name claims the voice.
                self._cancel_quietly()
            if self._use_thread:
                self._pending = (item.label, generation)
                if self._worker is None:
                    self._worker = threading.Thread(
                        target=self._work, name="mouthswitch-announce", daemon=True
                    )
                    self._worker.start()
                self._wake.notify()
        if not self._use_thread:
            self._say(item.label, generation)

    def stop(self) -> None:
        """The scan stopped: drop a pending name and cut one being said. Never raises."""
        with self._lock:
            self._generation += 1
            self._pending = None
            if self._speaking is not None:
                self._cancel_quietly()

    def close(self) -> None:
        """Stop and end the speech thread. Idempotent; never raises."""
        self.stop()
        with self._wake:
            self._closed = True
            worker, self._worker = self._worker, None
            self._wake.notify_all()
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=2.0)

    # ------------------------------------------------------------------ internals

    def _work(self) -> None:
        while True:
            with self._wake:
                while self._pending is None and not self._closed:
                    self._wake.wait()
                if self._closed:
                    return
                pending, self._pending = self._pending, None
            if pending is not None:
                self._say(*pending)

    def _say(self, text: str, generation: int) -> None:
        speak = self._speak
        if speak is None:
            return
        # One critical section decides whether this name still stands and claims the voice,
        # so a stop issued after it always finds `_speaking` set and cancels (kokoro.begin).
        with self._lock:
            if generation != self._generation or self._closed:
                return
            if self._begin is not None:
                try:
                    self._begin()
                except Exception:
                    log.debug("Mouth-Sound Switch: voice claim raised", exc_info=True)
            self._speaking = generation
        try:
            speak(text)
        except Exception:
            log.debug("Mouth-Sound Switch: speaking %r raised", text, exc_info=True)
        finally:
            with self._lock:
                if self._speaking == generation:
                    self._speaking = None

    def _cancel_quietly(self) -> None:
        """Stop the voice. Called under ``_lock``; ``cancel`` never takes it."""
        if self._cancel is None:
            return
        try:
            self._cancel()
        except Exception:
            log.debug("Mouth-Sound Switch: voice cancel raised", exc_info=True)
