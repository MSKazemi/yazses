"""Burst -> pitch contour -> command, with a non-word gate (pure) — ADR-v2-103.

``gesture.classify_contour`` classifies an F0 contour; nothing on main produced one. This module
runs :func:`yazses.audio.pitch.track` over a finished hold-to-talk burst and hands the voiced F0
to the core.

**A decision the original ADR did not contain** (recorded in its 2026-10-21 amendment). It says
how to classify a hum, not how to tell a hum from dictation. Every voiced word has an F0
contour — a spoken "no" falls — so classifying every burst would turn ordinary speech into
commands. :func:`is_nonword_voiced_burst` is the gate, and it fires only on a specific,
checkable signal (AGENTS.md rule 9), both halves required:

* **the transcript is empty or only hum spellings** (``hmm``, ``mm``, ``mhm``, ``uh``, ``um``,
  ``ah``, ``er``…, :func:`is_hum_transcript`). Any other word — including "no", "yes", "okay",
  and spellings that are also words or letters, such as "hum", "err", "em" or "u" — keeps the
  burst as dictation. A hum that the recognizer turns into some other word is a missed
  gesture, which is the cheap side of the error;
* **the audio is mostly voiced**: at least ``min_voiced_fraction`` of the burst's active frames
  (within ``ACTIVE_DB`` of its loud part) carry a pitch, and at least ``min_voiced_ms`` of them do.
  A hum is continuously voiced; a cough, a breath or a click is not.

The two open points the owner decided on 2026-10-21: a *flat* hum is unmapped by default, so a
lone thinking "hmm" does nothing; and with ``[contour]`` on the hum check runs before the #598
speech-presence discard, so a hum is not thrown away first (:mod:`yazses.contour.wiring`). The
thresholds here were checked on synthetic tones only, not on recorded hums.

Wired through :mod:`yazses.contour.wiring`; ``[contour]`` stays off by default.
"""
from __future__ import annotations

import re
from collections.abc import Sequence

import numpy as np

from yazses.audio.pitch import HOP_MS, PitchFrame, track
from yazses.contour.gesture import classify_contour, gesture_to_command, normalize_contour

#: One hum spelling: hm, hmm, mm, mhm, mm-hmm (split on the hyphen), uh, um, uhm, ah, er, erm, eh,
#: with letters repeated (hmmm, uhh, ahh). A spelling that is also a word or a letter — "hum",
#: "err", "em", "m", "u", "n" — is deliberately not a hum: it could be dictation.
_HUM_TOKEN = re.compile(
    r"^(?:(?:h+m+|m{2,}|m+h+m+)(?:h+m+)*"  # hm hmm mm mmm mhm mm-hmm hmhm; never a lone "m"
    r"|u+(?:h+m*|m+)"                       # uh uhh uhm um umm; never a lone "u"
    r"|a+h+"                                # ah ahh aah
    r"|erm*"                                # er erm ermm; never "err" (a verb) or "em"
    r"|e+h+)$"                              # eh ehh
)
#: Characters that never make a word: punctuation and the ellipsis a recognizer adds to a hum.
_NON_WORD = re.compile(r"[^\w\s-]+|_", re.UNICODE)
#: A frame is active when its RMS is within this many dB of the burst's 95th-percentile frame.
ACTIVE_DB = 20.0
MIN_VOICED_FRACTION = 0.8
MIN_VOICED_MS = 400.0
#: Median-filter width over the voiced F0, to remove single-frame octave slips.
SMOOTH_FRAMES = 5


def is_hum_transcript(text: str | None) -> bool:
    """True if ``text`` is empty or only hum spellings (case and punctuation ignored). Pure."""
    cleaned = _NON_WORD.sub(" ", (text or "").lower())
    tokens = [t for t in re.split(r"[\s-]+", cleaned) if t]
    return all(_HUM_TOKEN.match(t) for t in tokens)


def _active(frames: Sequence[PitchFrame]) -> list[PitchFrame]:
    if not frames:
        return []
    rms = np.array([f.rms for f in frames], dtype=float)
    ref = float(np.percentile(rms, 95))
    if ref <= 0.0:
        return []
    floor = ref * 10.0 ** (-ACTIVE_DB / 20.0)
    return [f for f, r in zip(frames, rms, strict=True) if r >= floor]


def is_mostly_voiced(frames: Sequence[PitchFrame], *,
                     min_voiced_fraction: float = MIN_VOICED_FRACTION,
                     min_voiced_ms: float = MIN_VOICED_MS, hop_ms: float = HOP_MS) -> bool:
    """True if the burst's active frames are mostly voiced and long enough to be a hum. Pure."""
    active = _active(frames)
    if not active:
        return False
    voiced = sum(1 for f in active if f.voiced)
    return voiced * hop_ms >= min_voiced_ms and voiced / len(active) >= min_voiced_fraction


def is_nonword_voiced_burst(transcript: str | None, frames: Sequence[PitchFrame], *,
                            min_voiced_fraction: float = MIN_VOICED_FRACTION,
                            min_voiced_ms: float = MIN_VOICED_MS,
                            hop_ms: float = HOP_MS) -> bool:
    """The non-word gate: a hum-only transcript *and* mostly-voiced audio. Pure."""
    return is_hum_transcript(transcript) and is_mostly_voiced(
        frames, min_voiced_fraction=min_voiced_fraction, min_voiced_ms=min_voiced_ms,
        hop_ms=hop_ms,
    )


def burst_contour(frames: Sequence[PitchFrame], smooth: int = SMOOTH_FRAMES) -> list[float]:
    """The voiced F0 (Hz) of a burst, median-smoothed over ``smooth`` voiced frames. Pure."""
    f0 = np.array([f.f0_hz for f in frames if f.voiced], dtype=float)
    if f0.size == 0 or smooth <= 1:
        return f0.tolist()
    half = smooth // 2
    padded = np.pad(f0, half, mode="edge")
    windows = np.lib.stride_tricks.sliding_window_view(padded, 2 * half + 1)
    return np.median(windows, axis=1).tolist()


def burst_gesture(frames: Sequence[PitchFrame], slope_threshold: float = 1.5) -> str:
    """``rise`` | ``fall`` | ``rise_fall`` | ``flat`` for a burst's frames. Pure."""
    return classify_contour(normalize_contour(burst_contour(frames)), slope_threshold)


def burst_to_command(transcript: str | None, audio, sample_rate: int = 16000, profile=None,
                     *, min_voiced_fraction: float = MIN_VOICED_FRACTION,
                     min_voiced_ms: float = MIN_VOICED_MS) -> str | None:
    """The command a hummed burst names, or ``None`` when it is not a non-word hum. Pure.

    The transcript check runs first: it costs nothing, and it rejects every ordinary dictation
    burst before any pitch is tracked.
    """
    if not is_hum_transcript(transcript):
        return None
    frames = track(audio, sample_rate)
    if not is_mostly_voiced(frames, min_voiced_fraction=min_voiced_fraction,
                            min_voiced_ms=min_voiced_ms):
        return None
    return gesture_to_command(burst_gesture(frames), profile)
