"""Play an earcon without ever getting in the way of dictation (ADR-v2-096).

`tones.py` decides *what* the motif is and renders it to a waveform. This decides
*whether and how* it reaches the speakers, which is where all the hazards are.

Three properties, and each one rules out the obvious implementation:

**It must not block the hot path.** `_on_hold_start` fires when the user presses the key
and every millisecond before capture begins is a millisecond of speech that is lost.
Playback therefore happens on a daemon thread and the caller never waits for it.

**It must not fail into the daemon.** No audio device, a busy device, a machine with no
speakers at all — these are ordinary situations, not errors, and none of them may
interrupt someone's dictation. Every failure is swallowed and logged at debug.

**It must not talk over itself.** Hold, release, hold again in quick succession would
otherwise stack three motifs on top of each other. A single-slot lock drops the new cue
rather than queueing it: an earcon that arrives late is worse than one that never played,
because it describes a state the system has already left.
"""

from __future__ import annotations

import logging
import threading

from yazses.earcon.tones import earcon_for, render_earcon

log = logging.getLogger(__name__)

#: Sample rate for playback. Matches `render_earcon`'s default.
_FS = 44100
#: Peak amplitude. Well below full scale on purpose — this is a cue that shares a room
#: with the user's voice and possibly a screen reader, not a notification chime.
_GAIN = 0.25


class EarconPlayer:
    """Plays short non-speech cues for daemon state changes.

    Constructed even when the feature is off (it is two fields), so the daemon has no
    ``None`` check on the hot path; `play` returns immediately unless enabled.
    """

    def __init__(self, enabled: bool = False) -> None:
        self._enabled = bool(enabled)
        self._busy = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self._enabled

    def play(self, event: str, confidence: float | None = None) -> None:
        """Play the motif for *event*, if one is due. Never blocks, never raises."""
        if not self._enabled:
            return
        if not self._busy.acquire(blocking=False):
            # Something is already sounding. Dropping is deliberate — see the module
            # docstring: a late cue describes a state the daemon has already left.
            return
        threading.Thread(
            target=self._render_and_play,
            args=(event, confidence),
            name="earcon",
            daemon=True,
        ).start()

    def _render_and_play(self, event: str, confidence: float | None) -> None:
        try:
            specs = earcon_for(event, confidence)
            if not specs:
                return
            wave = render_earcon(specs, fs=_FS)
            if wave.size == 0:
                return
            import sounddevice as sd

            sd.play(wave * _GAIN, samplerate=_FS, blocking=True)
        except Exception:
            # A missing or busy output device is an ordinary situation on a headless
            # box, in a container, or over SSH. It must never reach the dictation path.
            log.debug("Earcon playback failed for %r", event, exc_info=True)
        finally:
            self._busy.release()
