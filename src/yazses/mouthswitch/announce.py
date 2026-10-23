"""Hear the scan when it cannot be seen: a step cue and the item's name (ADR-v2-097).

The scan strip is drawn by the overlay, which does not run everywhere (a native Wayland
session, a base install without the ``desktop`` extra). Without it a click would select an
item nobody can see, so the switch used to refuse to start. This module lets the switch run
there *audibly* instead, with two existing outputs the daemon hands in:

* an **earcon cue** at every step (``[earcon]``, ADR-v2-096): ``scan_first`` when the scan
  is back at the first item, ``scan_step`` for every other item, so the steps can be counted;
* the item's **name, spoken** by the offline read-back voice (``[tts]``), when it can speak
  -- or, with ``[mouthswitch] speak_names`` and read-back off, by a voice built for the
  switch alone (:func:`switch_voice`), so the names are heard without your dictation being
  read back.

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

import copy
import dataclasses
import logging
import math
import threading
from collections.abc import Callable
from typing import Any

from yazses.mouthswitch.scanner import ScanItem

__all__ = [
    "FIRST_CUE",
    "SPEECH_LEAD_S",
    "SPEECH_S_PER_CHAR",
    "STEP_CUE",
    "SWITCH_VOICE_PURPOSE",
    "ScanAnnouncer",
    "cue_duration_s",
    "speech_duration_s",
    "switch_voice",
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

#: What the switch-only voice is called in the TTS factory's log line, so a user who never
#: turned read-back on is not told that read-back is on.
SWITCH_VOICE_PURPOSE = "Speaking the Mouth-Sound Switch's item names ([mouthswitch] speak_names)"


def _enabled_copy(tts_config: Any) -> Any:
    """A copy of ``[tts]`` with ``enabled`` on; the config the daemon holds is untouched."""
    if dataclasses.is_dataclass(tts_config) and not isinstance(tts_config, type):
        return dataclasses.replace(tts_config, enabled=True)
    clone = copy.copy(tts_config)
    clone.enabled = True
    return clone


def switch_voice(
    tts_config: Any,
    *,
    build: Callable[[Any], Any],
    files_present: Callable[[], bool],
) -> tuple[Any | None, str]:
    """A voice for the switch's item names alone, or ``(None, why)``. Never raises.

    For ``[mouthswitch] speak_names`` with read-back off. ``build`` is the factory read-back
    uses (``tts.factory.build_tts``), handed a *copy* of ``[tts]`` with ``enabled`` on: the
    voice, speed and model paths are the user's own ``[tts]`` settings, and ``[tts]`` itself
    stays off, so nothing that reads it -- dictation read-back above all -- turns on.

    It never fetches anything. The voice model's download is registered (ADR-019) as
    something enabling read-back does; ``speak_names`` is not that, so the model must
    already be on disk (``files_present``) or there is no voice. A backend that degraded to
    the silent null one (the ``tts`` extra missing, say) is no voice either; ``why`` is then
    ``""``, because the factory has already logged the reason, once.
    """
    try:
        present = bool(files_present())
    except Exception as exc:
        return None, f"could not check for the offline voice model ({type(exc).__name__})"
    if not present:
        return None, (
            "the offline voice model is not on this machine, and speak_names never "
            "downloads it; turn read-back on once to fetch it (`yazses features enable "
            "read-back`, then off again), or copy it in by hand (docs/how-to/air-gapped.md)"
        )
    try:
        voice = build(_enabled_copy(tts_config))
    except Exception as exc:
        return None, f"the offline voice could not start ({type(exc).__name__})"
    if voice is None or getattr(voice, "name", "null") == "null":
        return None, ""
    return voice, ""


def _seconds(value: object) -> float:
    """A duration, sanitised: ``0.0`` for anything that is not a finite positive number."""
    try:
        seconds = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return seconds if math.isfinite(seconds) and seconds > 0.0 else 0.0


def cue_duration_s() -> float:
    """How long the longer of the two step cues sounds, in seconds. Pure.

    The sum of its tones' durations: ``earcon/tones.py`` renders a motif's tones back to
    back. Read from the earcon table, never restated here. The audio device's own start-up
    latency is not counted -- it is not known, and the cue is tens of milliseconds.
    """
    from yazses.earcon.tones import earcon_for

    return max(sum(t.dur_ms for t in earcon_for(e)) for e in (FIRST_CUE, STEP_CUE)) / 1000.0


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
    claim is never lost. ``duration_s(text)`` is the estimate the scanner lengthens a step by;
    ``cue_s`` is how long the cue itself sounds (:func:`cue_duration_s`), counted when the
    cue plays, so a cue-only step also waits for its own tick to end. With ``thread=False`` the name is spoken inline -- the test path.
    """

    def __init__(
        self,
        *,
        cue: Callable[[str], None] | None = None,
        speak: Callable[[str], None] | None = None,
        cancel: Callable[[], None] | None = None,
        begin: Callable[[], None] | None = None,
        duration_s: Callable[[str], float] = speech_duration_s,
        cue_s: float = 0.0,
        thread: bool = True,
    ) -> None:
        self._cue = cue
        self._cue_s = _seconds(cue_s)
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
        """How long announcing ``item`` takes: the longer of its cue and its spoken name.

        Both start as the step begins. ``0.0`` with neither (or an estimate that fails).
        """
        cue = self._cue_s if self._cue is not None else 0.0
        if self._speak is None:
            return cue
        try:
            speech = _seconds(self._duration(item.label))
        except Exception:
            log.debug("Mouth-Sound Switch: announcement estimate raised", exc_info=True)
            speech = 0.0
        return max(cue, speech)

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
