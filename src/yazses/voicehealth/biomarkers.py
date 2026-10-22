"""Vocal-strain biomarkers and the session strain history (ADR-v2-034).

``strain.py`` scores jitter, shimmer and HNR and decides from a window of scores, but
nothing measured those three numbers. This module is the producer side, split the house
way:

- :class:`BiomarkerBackend` — the seam. A backend turns one utterance's audio into a
  :class:`Biomarkers` reading, or ``None`` when the audio does not support one.
- :class:`ParselmouthBiomarkers` — the Praat backend. ``parselmouth`` (the optional
  ``prosody`` extra) is imported inside :meth:`ParselmouthBiomarkers.measure`, never at
  module scope, so a base install imports this module fine and the backend simply
  reports ``None`` when the extra is missing.
- :class:`StrainHistory` — pure, dependency-free session state: a rolling window of
  per-utterance strain levels fed to :func:`~yazses.voicehealth.strain.should_suggest_break`,
  plus the extra conditions below. It keeps floats only — no audio is retained.
- :class:`StrainMonitor` — glue: backend → history, swallowing backend failures so a
  measurement problem can never break dictation.

**Deliberately conservative (AGENTS.md rule 9, ADR-021).** A break reminder interrupts
the user, and one that fires on an ordinary voice teaches them to dismiss it. The
thresholds in ``strain.py`` are rough sustained-vowel anchors, and dictation is
connected speech recorded through whatever microphone the user has, so an absolute
score alone is not a specific signal: a noisy mic or a naturally rough voice would
score high all day. :class:`StrainHistory` therefore suggests a break only when *all*
of these hold:

1. the config is enabled and the mean of the last ``min_samples`` measured utterances
   is at least ``threshold`` (the unchanged ``should_suggest_break`` rule);
2. that mean has risen at least ``min_rise`` above this session's *own* baseline — the
   mean of its first ``baseline_samples`` measured utterances — so a voice or mic that
   scores high from the start never fires; it is a drift detector, not a verdict on
   anyone's voice;
3. at least ``cooldown_s`` seconds have passed since the previous suggestion;
4. fewer than ``max_per_session`` suggestions have been made this session.

After a suggestion the window is cleared, so another needs a full fresh window. With
the default ``min_samples = 20`` the earliest possible suggestion is the 40th measured
utterance (20 for the baseline, then a full window). These defaults are unvalidated
against real users — calibration is an open item in the ADR — and they err toward
silence. Advisory only, never diagnostic.
"""
from __future__ import annotations

import logging
import math
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from yazses.voicehealth.strain import should_suggest_break, strain_level

log = logging.getLogger(__name__)

#: Default rise over the session baseline the recent mean must reach (strain units 0–1).
DEFAULT_MIN_RISE = 0.15
#: Default minimum gap between two suggestions, in seconds (45 minutes).
DEFAULT_COOLDOWN_S = 45 * 60.0
#: Default cap on suggestions per session.
DEFAULT_MAX_PER_SESSION = 2

#: Text a caller can show when :meth:`StrainHistory.observe` returns True. Kept under the
#: 256-character limit past which a Windows balloon silently disappears.
BREAK_SUGGESTION_TITLE = "Time for a voice break?"
BREAK_SUGGESTION_BODY = (
    "Your voice measurements have drifted up over this session. A short break and "
    "some water may help. This is an advisory reminder, not a diagnosis."
)


@dataclass(frozen=True)
class Biomarkers:
    """One utterance's voice-quality reading.

    ``jitter`` and ``shimmer`` are Praat's *local* measures as fractions (0.01 = 1%);
    ``hnr`` is the mean harmonics-to-noise ratio in dB — the units
    :func:`~yazses.voicehealth.strain.strain_level` expects.
    """

    jitter: float
    shimmer: float
    hnr: float

    def is_finite(self) -> bool:
        return all(math.isfinite(v) for v in (self.jitter, self.shimmer, self.hnr))

    def strain(self) -> float:
        return strain_level(self.jitter, self.shimmer, self.hnr)


class BiomarkerBackend(Protocol):
    """Measures :class:`Biomarkers` from one utterance of mono audio."""

    def measure(self, audio: Any, sample_rate: int) -> Biomarkers | None:
        """Return a reading, or ``None`` when the audio cannot support one."""


class _StrainConfig(Protocol):
    """The fields of the ``[voicehealth]`` config section this module reads."""

    enabled: bool
    threshold: float
    min_samples: int


class ParselmouthBiomarkers:
    """Praat (``parselmouth``) backend: local jitter, local shimmer, mean HNR.

    Uses Praat's standard voice-report commands: ``To PointProcess (periodic, cc)`` for
    glottal periods, ``Get jitter (local)`` and ``Get shimmer (local)`` over them, and
    ``To Harmonicity (cc)`` → ``Get mean`` for HNR. Returns ``None`` — never raises — when
    the extra is not installed, the audio has fewer than ``min_periods`` voiced periods
    (too short or mostly unvoiced to say anything), or Praat returns an undefined value.
    """

    def __init__(
        self,
        *,
        pitch_floor_hz: float = 75.0,
        pitch_ceiling_hz: float = 500.0,
        min_periods: int = 50,
    ) -> None:
        self.pitch_floor_hz = float(pitch_floor_hz)
        self.pitch_ceiling_hz = float(pitch_ceiling_hz)
        self.min_periods = int(min_periods)

    def measure(self, audio: Any, sample_rate: int) -> Biomarkers | None:
        try:
            import numpy as np
            import parselmouth  # type: ignore  # optional `prosody` extra
            from parselmouth.praat import call  # type: ignore
        except Exception:  # noqa: BLE001 — absent extra means "no reading", not an error
            return None

        try:
            samples = np.asarray(audio, dtype="float64").reshape(-1)
            if samples.size == 0:
                return None
            sound = parselmouth.Sound(samples, sampling_frequency=float(sample_rate))
            lo, hi = self.pitch_floor_hz, self.pitch_ceiling_hz
            points = call(sound, "To PointProcess (periodic, cc)", lo, hi)
            periods = call(points, "Get number of periods", 0, 0, 0.0001, 0.02, 1.3)
            if not periods or int(periods) < self.min_periods:
                return None
            jitter = call(points, "Get jitter (local)", 0, 0, 0.0001, 0.02, 1.3)
            shimmer = call(
                [sound, points], "Get shimmer (local)", 0, 0, 0.0001, 0.02, 1.3, 1.6
            )
            harmonicity = call(sound, "To Harmonicity (cc)", 0.01, lo, 0.1, 1.0)
            hnr = call(harmonicity, "Get mean", 0, 0)
            reading = Biomarkers(float(jitter), float(shimmer), float(hnr))
        except Exception as exc:  # noqa: BLE001 — a measurement must never break dictation
            log.debug("voicehealth biomarker extraction failed: %s", exc)
            return None
        return reading if reading.is_finite() else None


class StrainHistory:
    """Pure per-session strain history and break decision. See the module docstring.

    ``config`` is the ``[voicehealth]`` section (``enabled``, ``threshold``,
    ``min_samples``); the window length is ``min_samples``. ``now`` passed to
    :meth:`observe` is any monotonic clock in seconds, injected so this stays pure.
    """

    def __init__(
        self,
        config: _StrainConfig,
        *,
        baseline_samples: int | None = None,
        min_rise: float = DEFAULT_MIN_RISE,
        cooldown_s: float = DEFAULT_COOLDOWN_S,
        max_per_session: int = DEFAULT_MAX_PER_SESSION,
    ) -> None:
        self._config = config
        window = max(1, int(getattr(config, "min_samples", 20)))
        self._baseline_target = window if baseline_samples is None else max(1, baseline_samples)
        self._min_rise = float(min_rise)
        self._cooldown_s = float(cooldown_s)
        self._max_per_session = int(max_per_session)
        self._window: deque[float] = deque(maxlen=window)
        self._baseline: list[float] = []
        self._last_suggested: float | None = None
        self._suggestions = 0

    @property
    def baseline(self) -> float | None:
        """The session baseline strain, or ``None`` until it is complete."""
        if len(self._baseline) < self._baseline_target:
            return None
        return sum(self._baseline) / len(self._baseline)

    @property
    def window(self) -> tuple[float, ...]:
        return tuple(self._window)

    @property
    def suggestions(self) -> int:
        return self._suggestions

    def reset(self) -> None:
        """Start a new session: forget the baseline, the window and the cooldown."""
        self._window.clear()
        self._baseline.clear()
        self._last_suggested = None
        self._suggestions = 0

    def observe(self, reading: Biomarkers | float, now: float) -> bool:
        """Record one utterance and return True when a break should be suggested now.

        ``reading`` is a :class:`Biomarkers` or an already-computed strain level.
        Non-finite values are ignored, including a :class:`Biomarkers` with any NaN or
        infinite field (its strain score would otherwise be clamped to a finite number).
        The first ``baseline_samples`` readings build the session baseline and never fire.
        """
        if isinstance(reading, Biomarkers):
            if not reading.is_finite():
                return False
            level = reading.strain()
        else:
            level = float(reading)
        if not math.isfinite(level):
            return False
        level = min(1.0, max(0.0, level))
        if len(self._baseline) < self._baseline_target:
            self._baseline.append(level)
            return False
        self._window.append(level)
        if not self._may_fire(now):
            return False
        window = list(self._window)
        if not should_suggest_break(window, self._config):
            return False
        baseline = self.baseline
        if baseline is None or (sum(window) / len(window)) - baseline < self._min_rise:
            return False
        self._suggestions += 1
        self._last_suggested = now
        self._window.clear()
        return True

    def _may_fire(self, now: float) -> bool:
        if self._suggestions >= self._max_per_session:
            return False
        if self._last_suggested is not None and now - self._last_suggested < self._cooldown_s:
            return False
        return True


class StrainMonitor:
    """Backend → history glue for one session. Never raises out of :meth:`on_utterance`."""

    def __init__(self, backend: BiomarkerBackend, history: StrainHistory) -> None:
        self._backend = backend
        self.history = history

    def on_utterance(self, audio: Sequence[float] | Any, sample_rate: int, now: float) -> bool:
        """Measure one utterance and return True when a break should be suggested."""
        try:
            reading = self._backend.measure(audio, sample_rate)
        except Exception as exc:  # noqa: BLE001 — a measurement must never break dictation
            log.debug("voicehealth backend raised: %s", exc)
            return False
        if reading is None or not reading.is_finite():
            return False
        return self.history.observe(reading, now)
