"""Is there any speech in this burst at all? The gate between "loud enough" and "decode".

The energy gate (:mod:`yazses.audio.vad_calibrated`) answers *"is it louder than the room
was when you calibrated"*, which a fan, a keyboard, a chair, or the key being pressed
all satisfy. Handed such a burst, Whisper does not return nothing. It returns the
tokens it was primed with: measured on synthetic no-speech audio (seeded white, brown
and low-frequency noise and clicks, 0.5-3 s, mean level 0.01-0.03, no speech anywhere)
the built-in vocabulary prompt came back as the transcript, whole or in fragments
("The app is called YazSes.", "The app is called YazS."), from every model tried
(``small``, ``base.en``, ``tiny.en``); a personal vocabulary came back the same way
("Ydotool, ydotool, Mohsen, Wayland."), as did "Thanks for watching." (#598). The model's
own ``no_speech_prob`` for those segments ran 0.43-0.97, against 0.02-0.27 for
real speech: too close to cut on, because the prompt pulls it *down*.

So this asks the question with a speech detector rather than a level: Silero, which
``faster-whisper`` already bundles (nothing is downloaded, nothing leaves the machine).
On the same noise it found speech in 1 of 48 bursts; on a public-domain speech sample
it found speech in every case tried, down to 2% volume and a 0.3 s snippet.

The policy here is pure and the detector is injected, so it is tested without a model.
It **fails open**: a detector that cannot run, raises, or does not apply to this sample
rate means "decode as before", because dropping a sentence someone said is the worse
error. Modes that exist for voices a general detector under-hears are exempt by the
caller (:func:`speech_check_applies`).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

#: ``(audio, sample_rate) -> True`` when no speech was found, ``None`` when unknown.
Detector = Callable[[Any, int], "bool | None"]


#: Silero's speech-probability cut for this gate. The library default is 0.5; this is lower
#: on purpose, because here a false "no speech" costs words someone said while a false
#: "speech" costs only today's behaviour. Measured 2026-10-18 on the public-domain JFK
#: sample cut into 22 single-word bursts (0.15 s either side, as a press and release
#: leaves them) and on 27 seeded noise bursts (white, brown, hum; 0.5-3 s; level 0.012-0.08):
#:
#:     threshold   voiced words dropped   whisper-proxy words dropped   noise passed as speech
#:               (normal / 10% volume)        (normal volume)
#:     0.5            0 / 2 of 22                  9 of 22                    0 of 27
#:     0.3            0 / 0 of 22                  3 of 22                    0 of 27
#:     0.2            0 / 0 of 22                  2 of 22                    1 of 27
#:     0.1            0 / 0 of 22                  0 of 22                    5 of 27
#:
#: 0.3 is the knee: nothing voiced is lost and no noise gets through. The "whisper proxy" is
#: the same sample resynthesised with random phase (voicing destroyed, envelope kept): a
#: crude stand-in, not whispered speech, and it is why whisper users are exempt by mode.
SPEECH_THRESHOLD = 0.3


def _default_detector(audio: Any, sample_rate: int) -> bool | None:
    from yazses.recimport.audio_io import holds_no_speech

    return holds_no_speech(audio, sample_rate, threshold=SPEECH_THRESHOLD)


def speech_check_applies(
    *,
    enabled: bool,
    whisper_mode: bool = False,
    dysfluency_friendly: bool = False,
    sotto_voce: bool = False,
) -> bool:
    """Whether to run the check on this burst.

    Off for the modes built for speech a general detector may under-hear: Whisper /
    Low-Effort mode (its energy gate is lowered for the same reason), Dysfluency-Friendly
    mode, and the sotto-voce command channel, where a *whispered* burst is a command.
    Those users keep today's behaviour, prompt echoes included, rather than risk losing
    what they said.
    """
    return enabled and not (whisper_mode or dysfluency_friendly or sotto_voce)


def holds_no_speech(
    audio: Any, sample_rate: int, *, detector: Detector | None = None
) -> bool:
    """True only when the detector *positively* found no speech. Never raises.

    ``None`` from the detector (unavailable, wrong sample rate) and any exception both
    read as "cannot tell", which is ``False``: the burst is decoded.
    """
    try:
        verdict = (detector or _default_detector)(audio, sample_rate)
    except Exception:  # noqa: BLE001 - a gate must never break dictation
        return False
    return verdict is True
