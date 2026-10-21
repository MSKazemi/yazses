"""Mouth-sound onset detector + feature extractor (pure numpy, no model) — ADR-v2-097.

``scan.classify_mouth_sound`` names a sound from four features (``duration_ms``, ``centroid_hz``,
``zcr``, ``burst``) and nothing on main produced them. This module is that producer: it watches
an idle audio stream (chunks of any size, the recorder does not fix a block size), cuts out each
short isolated sound, measures the features, asks the classifier, and maps the kind to a
scan-selector switch (``advance`` / ``select``).

The detector interrupts nobody when it is quiet and moves a highlight when it fires, so a false
fire is the expensive error (AGENTS.md rule 9). It therefore emits only when *every* one of these
specific, checkable conditions holds, and is silent otherwise:

* **isolation before** — the onset follows at least ``PRE_QUIET_MS`` of quiet. A word-final stop
  release after its closure, or a fricative inside a word, does not qualify;
* **isolation after** — the sound is followed by ``POST_QUIET_MS`` of quiet before it is emitted.
  A plosive that runs into a vowel stays one segment and that segment is voiced (below);
* **not after speech** — fewer than ``PITCHED_FRAMES`` voiced 40 ms frames in the
  ``CONTEXT_MS`` before the onset. A stop release a little more than ``PRE_QUIET_MS`` after a
  word belongs to that word; the synthetic speech stand-in produced exactly this false fire
  before the guard existed;
* **short** — it lasts at most ``MAX_EVENT_MS``. A sentence, a hum, or a burst of fan noise
  overruns, is abandoned, and the detector waits for quiet again;
* **unvoiced** — no more than ``MAX_VOICED_FRACTION`` of its 40 ms frames, and fewer than
  ``PITCHED_FRAMES`` of them, carry a pitch, by the YIN tracker in :mod:`yazses.audio.pitch`.
  Any syllable with a vowel is voiced and rejected — including a long fricative glued to a
  short quiet vowel, which a fraction alone let through once in 30 synthetic minutes;
* **classified** — ``classify_mouth_sound`` names a kind, and the kind is mapped to an action;
* **refractory** — no second event within ``REFRACTORY_MS`` of the last one's end, so one
  physical sound (and its room echo) is one switch press.

The noise floor is tracked from quiet frames (an exponential average), so a gradual rise in a
fan or hiss raises the floor rather than firing. A *step* up of more than ``SUSTAIN_RATIO`` (a
fan switching on, or a stream that opens with digital zeros before the room noise starts) makes
every frame "sounding", so no quiet frame is left to update it from; after ``FLOOR_RESEED_MS``
with no floor update the floor is re-seeded from the quietest frame of that window, and the
detector hears again instead of going deaf for good. Levels and thresholds are signal-processing defaults
checked on synthetic signals (``tests/test_mouthswitch_detect.py``); they have **not** been
measured on recorded mouth sounds or real speech. Local audio only; nothing is stored.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from yazses.audio.pitch import yin_f0
from yazses.mouthswitch.scan import classify_mouth_sound

#: Energy frame for onset/offset tracking. Short, so a 5 ms click is resolved.
FRAME_MS = 5
#: An onset needs this many times the noise floor, and at least ``ONSET_MIN_RMS``.
ONSET_RATIO = 8.0
ONSET_MIN_RMS = 2e-3
#: A frame counts as still-sounding above this many times the floor.
SUSTAIN_RATIO = 3.0
#: Quiet needed before an onset counts, and after a sound before it is emitted.
PRE_QUIET_MS = 150
POST_QUIET_MS = 150
#: Longest a sound may take to climb from the sustain level to the onset level.
RISE_MS = 30
#: Longest sound that can be a switch press; anything longer is speech or noise.
MAX_EVENT_MS = 500
#: A ``burst`` reaches its peak this fast and stands this far over the floor.
BURST_RISE_MS = 20
BURST_RATIO = 10.0
#: A sound is voiced when more than this share of its 40 ms frames carry a pitch, or when
#: ``PITCHED_FRAMES`` of them do (a long "sh" glued to a short, quiet vowel).
MAX_VOICED_FRACTION = 0.25
PITCHED_FRAMES = 2
VOICING_FRAME_MS = 40
VOICING_HOP_MS = 10
#: Audio before an onset read for voicing; ``PITCHED_FRAMES`` voiced frames in it reject it.
CONTEXT_MS = 400
#: Dead time after an emitted event.
REFRACTORY_MS = 300
#: Noise-floor tracking: EMA weight per quiet frame, and the floor for digital silence.
FLOOR_ALPHA = 0.05
FLOOR_MIN = 1e-5
#: Frames used to seed the floor before any onset may count.
WARMUP_MS = 100
#: With no quiet frame to update the floor from for this long, re-seed it from the quietest
#: frame of the window. Every frame of that window then stood over ``SUSTAIN_RATIO`` x floor,
#: so the re-seed can only raise the floor (less sensitive, never a new fire on its own).
FLOOR_RESEED_MS = 1000

#: The ADR's mapping: "pop" advances the highlight, a tongue click selects. ``sh`` is
#: recognised but unmapped by default — a sustained broadband hiss is the kind most easily
#: confused with room noise, so a user opts it in by passing their own mapping.
DEFAULT_ACTIONS: Mapping[str, str] = {"pop": "advance", "click": "select"}


@dataclass(frozen=True)
class MouthSoundEvent:
    """One classified, isolated mouth sound.

    ``t_s`` is the onset, in seconds since the first sample fed after the last reset.
    ``action`` is ``None`` when ``kind`` has no mapping (the event is still reported).
    """

    t_s: float
    kind: str
    action: str | None
    duration_ms: float
    centroid_hz: float
    zcr: float
    flatness: float
    burst: bool
    voiced_fraction: float


def zero_crossing_rate(x) -> float:
    """Share of adjacent sample pairs whose sign differs, in ``[0, 1]``. Pure."""
    a = np.asarray(x, dtype=np.float64).ravel()
    if a.size < 2:
        return 0.0
    s = np.signbit(a)
    return float(np.count_nonzero(s[1:] != s[:-1]) / (a.size - 1))


def _power_spectrum(x: np.ndarray) -> np.ndarray:
    return np.abs(np.fft.rfft(x * np.hanning(x.size))) ** 2


def spectral_centroid(x, sample_rate: int) -> float:
    """Power-weighted mean frequency (Hz) of a Hann-windowed segment; ``0.0`` if silent. Pure."""
    a = np.asarray(x, dtype=np.float64).ravel()
    if a.size < 2:
        return 0.0
    p = _power_spectrum(a)
    total = float(p.sum())
    if total <= 0.0:
        return 0.0
    return float((np.fft.rfftfreq(a.size, 1.0 / sample_rate) * p).sum() / total)


def spectral_flatness(x) -> float:
    """Geometric over arithmetic mean of the power spectrum, in ``[0, 1]``. Pure.

    ``~1`` for white noise, near ``0`` for a tone. ``0.0`` for a silent segment.
    """
    a = np.asarray(x, dtype=np.float64).ravel()
    if a.size < 2:
        return 0.0
    p = _power_spectrum(a)[1:] + 1e-20
    mean = float(p.mean())
    if mean <= 1e-19:
        return 0.0
    return float(min(1.0, np.exp(np.mean(np.log(p))) / mean))


def voiced_frames(x, sample_rate: int) -> tuple[int, int]:
    """``(voiced, total)`` 40 ms / 10 ms-hop frames, voiced by YIN. Pure."""
    a = np.asarray(x, dtype=np.float64).ravel()
    frame = int(sample_rate * VOICING_FRAME_MS / 1000)
    hop = int(sample_rate * VOICING_HOP_MS / 1000)
    if a.size < frame:
        return 0, 0
    n = 1 + (a.size - frame) // hop
    voiced = sum(1 for i in range(n) if yin_f0(a[i * hop:i * hop + frame], sample_rate)[0] > 0.0)
    return voiced, n


def voiced_fraction(x, sample_rate: int) -> float:
    """Share of 40 ms / 10 ms-hop frames YIN calls voiced; ``0.0`` if none fit. Pure."""
    voiced, n = voiced_frames(x, sample_rate)
    return voiced / n if n else 0.0


def extract_features(segment, sample_rate: int, floor_rms: float, *,
                     voicing_audio=None) -> dict:
    """Measure one cut-out sound -> the classifier's features plus diagnostics. Pure.

    ``segment`` is the sounding part (onset to last sounding frame); ``floor_rms`` the noise
    floor just before the onset. ``voicing_audio`` (default: ``segment``) is what the voicing
    check reads — the detector passes the segment plus its trailing quiet so a sound shorter
    than one 40 ms pitch frame can still be checked.
    """
    x = np.asarray(segment, dtype=np.float64).ravel()
    frame = max(1, int(sample_rate * FRAME_MS / 1000))
    n = max(1, x.size // frame)
    rms = np.sqrt(np.mean(x[:n * frame].reshape(n, frame) ** 2, axis=1)) if x.size >= frame \
        else np.array([float(np.sqrt(np.mean(x ** 2))) if x.size else 0.0])
    peak_i = int(np.argmax(rms))
    burst = (peak_i * FRAME_MS <= BURST_RISE_MS
             and float(rms[peak_i]) >= BURST_RATIO * max(floor_rms, FLOOR_MIN))
    v, total = voiced_frames(x if voicing_audio is None else voicing_audio, sample_rate)
    vf = v / total if total else 0.0
    return {
        "duration_ms": 1000.0 * x.size / sample_rate,
        "centroid_hz": spectral_centroid(x, sample_rate),
        "zcr": zero_crossing_rate(x),
        "flatness": spectral_flatness(x),
        "burst": bool(burst),
        "voiced_fraction": vf,
        "voiced": vf > MAX_VOICED_FRACTION or v >= PITCHED_FRAMES,
    }


class MouthSoundDetector:
    """Chunk-in, :class:`MouthSoundEvent`-out streaming detector. Pure state, no threads.

    ``actions`` maps a classifier kind to a switch action; a kind it omits is reported with
    ``action=None``. Feed it the idle microphone stream; it never touches the device itself.
    """

    def __init__(self, sample_rate: int = 16000,
                 actions: Mapping[str, str] | None = None) -> None:
        self.sample_rate = int(sample_rate)
        self.actions = dict(DEFAULT_ACTIONS if actions is None else actions)
        self._frame = max(1, int(self.sample_rate * FRAME_MS / 1000))
        self.reset()

    def reset(self) -> None:
        self._pending = np.zeros(0, dtype=np.float64)
        self._frames_seen = 0
        self._floor: float | None = None
        self._quiet_run = 0              # consecutive quiet frames
        self._state = "idle"             # idle | active | overrun
        self._seg: list[np.ndarray] = []  # frames since onset (sounding + trailing quiet)
        self._onset_frame = 0
        self._last_sounding = 0          # index into _seg of the last sounding frame
        self._onset_floor = FLOOR_MIN
        self._refractory_until = -1      # frame index
        self._history: deque[np.ndarray] = deque(maxlen=self._ms_to_frames(CONTEXT_MS) + 1)
        self._context = np.zeros(0)      # the audio before the current onset
        self._rise: list[np.ndarray] = []  # sub-onset sounding frames just before an onset
        self._rise_quiet = 0             # the quiet run that preceded the current rise
        self._stuck = 0                  # consecutive frames without a floor update
        self._recent_rms: deque[float] = deque(maxlen=self._ms_to_frames(FLOOR_RESEED_MS))

    # -- frame bookkeeping -------------------------------------------------------------------
    def _ms_to_frames(self, ms: float) -> int:
        return max(1, int(round(ms / FRAME_MS)))

    def _update_floor(self, rms: float) -> None:
        self._stuck = 0
        if self._floor is None:
            self._floor = max(rms, FLOOR_MIN)
        else:
            self._floor = max(FLOOR_MIN, (1 - FLOOR_ALPHA) * self._floor + FLOOR_ALPHA * rms)

    def feed(self, chunk) -> list[MouthSoundEvent]:
        """Consume a chunk of mono samples; return the events completed in it."""
        x = np.asarray(chunk, dtype=np.float64).ravel()
        if x.size and not np.all(np.isfinite(x)):
            x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)
        buf = np.concatenate([self._pending, x])
        n = buf.size // self._frame
        self._pending = buf[n * self._frame:]
        events: list[MouthSoundEvent] = []
        for i in range(n):
            ev = self._step(buf[i * self._frame:(i + 1) * self._frame])
            if ev is not None:
                events.append(ev)
        return events

    def _step(self, frame: np.ndarray) -> MouthSoundEvent | None:
        idx = self._frames_seen
        self._frames_seen += 1
        rms = float(np.sqrt(np.mean(frame * frame)))
        self._recent_rms.append(rms)
        self._stuck += 1                 # reset by _update_floor on a quiet frame
        if (self._state != "active" and self._floor is not None
                and self._stuck >= self._ms_to_frames(FLOOR_RESEED_MS)):
            # A step up in the background left no quiet frame to track it from. Every frame in
            # the window sounded, so its minimum is above the old floor: re-seed from it.
            self._floor = max(FLOOR_MIN, min(self._recent_rms))
            self._stuck = 0
        floor = self._floor if self._floor is not None else max(rms, FLOOR_MIN)
        sounding = rms > floor * SUSTAIN_RATIO
        onset = rms > max(floor * ONSET_RATIO, ONSET_MIN_RMS)

        # Every frame, in every state: a voiced segment that was itself rejected is exactly the
        # speech a following release must be checked against.
        self._history.append(frame)
        if self._state == "idle":
            if sounding and not onset:
                # A rising edge between the sustain and onset levels (an "sh" fading in). It
                # belongs to the onset that follows within RISE_MS, so it must not count as the
                # noise that breaks that onset's isolation; a slower swell is not a switch.
                if not self._rise:
                    self._rise_quiet = self._quiet_run
                self._rise.append(frame)
                self._quiet_run = 0
                if len(self._rise) > self._ms_to_frames(RISE_MS):
                    self._rise = []
                return None
            if onset:
                rise, self._rise = self._rise, []
                quiet_before = self._rise_quiet if rise else self._quiet_run
                self._quiet_run = 0
                if (idx >= self._ms_to_frames(WARMUP_MS)
                        and quiet_before >= self._ms_to_frames(PRE_QUIET_MS)
                        and idx - len(rise) >= self._refractory_until):
                    self._state = "active"
                    self._seg = rise + [frame]
                    self._onset_frame = idx - len(rise)
                    self._last_sounding = len(self._seg) - 1
                    self._onset_floor = floor
                    # The rise and onset are the newest history entries; the context precedes.
                    before = list(self._history)[:-len(self._seg)]
                    self._context = np.concatenate(before) if before else np.zeros(0)
                return None
            self._rise = []
            self._quiet_run += 1
            self._update_floor(rms)
            return None

        if self._state == "overrun":
            if sounding:
                self._quiet_run = 0
            else:
                self._quiet_run += 1
                self._update_floor(rms)
                if self._quiet_run >= self._ms_to_frames(PRE_QUIET_MS):
                    self._state = "idle"
            return None

        # active
        self._seg.append(frame)
        if sounding:
            self._last_sounding = len(self._seg) - 1
            self._quiet_run = 0
            if len(self._seg) * FRAME_MS > MAX_EVENT_MS:
                self._state = "overrun"
                self._seg = []
            return None
        self._quiet_run += 1
        if self._quiet_run < self._ms_to_frames(POST_QUIET_MS):
            return None
        # Isolated and finished: measure it. The quiet run counts toward the next onset's
        # isolation, so the state goes straight back to idle with ``_quiet_run`` kept.
        seg = np.concatenate(self._seg[:self._last_sounding + 1])
        # Voicing reads the sound itself, extended into the trailing quiet only as far as one
        # pitch frame needs: padding a 60 ms hum with 150 ms of quiet would dilute its voiced
        # share below the threshold and let a short "uh" through as a pop.
        min_voicing = int(self.sample_rate * VOICING_FRAME_MS / 1000)
        tail = np.concatenate(self._seg)[:max(seg.size, min_voicing)]
        onset_frame, onset_floor = self._onset_frame, self._onset_floor
        self._state = "idle"
        self._seg = []
        feats = extract_features(seg, self.sample_rate, onset_floor, voicing_audio=tail)
        end_frame = onset_frame + self._last_sounding + 1
        self._refractory_until = end_frame + self._ms_to_frames(REFRACTORY_MS)
        if feats["voiced"]:
            return None
        if voiced_frames(self._context, self.sample_rate)[0] >= PITCHED_FRAMES:
            return None
        kind = classify_mouth_sound(feats)
        if kind is None:
            return None
        return MouthSoundEvent(
            t_s=onset_frame * self._frame / self.sample_rate,
            kind=kind,
            action=self.actions.get(kind),
            duration_ms=feats["duration_ms"],
            centroid_hz=feats["centroid_hz"],
            zcr=feats["zcr"],
            flatness=feats["flatness"],
            burst=feats["burst"],
            voiced_fraction=feats["voiced_fraction"],
        )


def detect(audio, sample_rate: int = 16000, **kwargs) -> list[MouthSoundEvent]:
    """Run a fresh :class:`MouthSoundDetector` over a whole signal. Pure."""
    det = MouthSoundDetector(sample_rate, **kwargs)
    return det.feed(audio)
