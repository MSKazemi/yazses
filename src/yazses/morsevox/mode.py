"""Vocal Morse mode: when to start decoding Morse, and when to stop (pure) — ADR-v2-105.

`segment.py` turns a level stream into letters. Nothing decided *when* that stream should
be read as Morse rather than ignored, and the users this is for may be unable to press a
key to say so. This module is that decision, as a small state machine over the same
``(timestamp_ms, level)`` samples, with time supplied only by the caller:

* **idle** — not decoding. If the hum trigger is on, a :class:`HumDetector` listens for
  the entry signal: a *long, steady* voiced tone.
* **armed** — entry was asked for (a hum, or the spoken "morse mode"); waiting for the
  sound to stop, so the entry hum itself is never decoded as a dash.
* **morse** — every sample goes to a fresh :class:`~yazses.morsevox.segment.MorseStream`
  and the text it completes is returned for the caller to type. A silence of
  ``exit_silence_ms`` with no accepted pulse returns to idle, and so does the
  end-of-work prosign SK (``...-.-`` keyed as one character).

**The entry hum must not fire on ordinary speech (ADR-021, AGENTS.md rule 9).** A guard
that fires on a sentence teaches people to switch it off, so the rule is a specific,
checkable signal, never a guess. All three must hold over the last ``entry_hum_ms``:

1. **Unbroken.** Every sample since the run began is at or above ``off_level`` (the run
   starts at ``on_level``; the segmenter's hysteresis pair). Speech drops below the voice
   threshold between words and usually between syllables; one such drop restarts the run.
2. **Steady.** The coefficient of variation (population std / mean) of the levels in the
   window is at most ``max_hum_cv`` (default 0.25). Running speech is amplitude-modulated
   at the syllable rate, so even a breathless sentence with no gap fails this; a held
   "mmmm" does not.
3. **Enough evidence.** At least ``min_hum_samples`` samples in the window, so a stream
   with very long chunks cannot pass the steadiness test on two numbers.

**These thresholds are synthetic-only.** ``max_hum_cv`` and the 1.5 s default were chosen
on synthetic level streams (tests/test_morsevox_mode.py) and have not been measured on a
real voice, a real room or a real speaker who has trouble sustaining a tone. That is the
first thing to measure before anyone relies on this.

**Exit.** A silence of ``exit_silence_ms`` with no accepted pulse. It must be longer than
the word gap, or every space between words would end the mode; :func:`resolve` raises it
when it is not. Or the prosign **SK** (``...-.-``, end of work), keyed as one character
with no letter gap between S and K: it is not typed, and the mode ends with reason
``"prosign"`` as soon as the letter gap after it elapses, without waiting out the exit
silence. SK is matched only as a whole character, so "s" and "k" keyed with a letter gap
between them are still typed (the rule is in `decode.py`'s docstring). The caller can
also end the mode explicitly (:meth:`MorseMode.exit`) — when dictation starts, on a
hands-free pause, at shutdown.

Pure: no audio, no numpy, no clock, no daemon. Same shape as `segment.py`.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

from yazses.morsevox.decode import MorseCalib
from yazses.morsevox.segment import MorseStream, PulseSegmenter, SegmenterConfig

__all__ = [
    "ARMED",
    "ARMED_TIMEOUT_MS",
    "DEFAULT_ENTRY_HUM_S",
    "DEFAULT_EXIT_SILENCE_S",
    "ENTER_PHRASE",
    "IDLE",
    "MAX_HUM_CV",
    "MIN_HUM_SAMPLES",
    "MORSE",
    "HumDetector",
    "ModeConfig",
    "ModeStep",
    "MorseMode",
    "describe_status",
    "is_enter_phrase",
    "resolve",
]

IDLE = "idle"
ARMED = "armed"
MORSE = "morse"

#: PROVISIONAL defaults (owner decision 2026-10-22), synthetic-only — see the module docstring.
DEFAULT_ENTRY_HUM_S = 1.5
DEFAULT_EXIT_SILENCE_S = 3.0
#: Steadiness: the largest std/mean of the level over the hum window that still counts as a hum.
MAX_HUM_CV = 0.25
#: The fewest level samples a hum window may be judged on.
MIN_HUM_SAMPLES = 8
#: How long "armed" may wait for the sound to stop. A level that never falls below the
#: threshold (a fan, a hum that never ends) is not a state Morse can be decoded in.
ARMED_TIMEOUT_MS = 10_000.0
#: How much longer than the word gap the exit silence is forced to be, when it is not.
_EXIT_MARGIN_MS = 1000.0

#: The spoken entry command, matched as the WHOLE utterance (see :func:`is_enter_phrase`).
ENTER_PHRASE = "morse mode"


def is_enter_phrase(text: str) -> bool:
    """Is this whole transcribed utterance the spoken "morse mode" command? Pure.

    The same whole-utterance equality as the hands-free stop word
    (`handsfree/stopword.matches`): case, edge punctuation and hyphenation are forgiven,
    nothing else. "Morse mode." enters; "switch to morse mode please" and any sentence
    that merely contains the words is dictation and is typed.
    """
    from yazses.handsfree.stopword import matches

    return matches(text or "", ENTER_PHRASE)


def describe_status(block: dict) -> str:
    """One line for `yazses status` from the daemon's ``morse`` block. Pure; never raises.

    Built from flags only: the block carries no decoded text and neither does this line.
    """
    if not isinstance(block, dict):
        return "unknown"
    if block.get("fault"):
        return f"stopped ({block['fault']}) — run `yazses handsfree resume`"
    if block.get("active") is True:
        how = {"hum": "a long hum", "command": "\"morse mode\""}.get(
            str(block.get("entered_by")), "")
        return "ON — decoding Morse" + (f" (entered by {how})" if how else "")
    if block.get("paused") is True:
        return "off — paused (`yazses handsfree resume` to listen again)"
    if block.get("hum_entry") is True:
        if block.get("listening") is True:
            return "off — listening for a long steady hum, or say \"morse mode\""
        return "off — not listening for the hum (microphone not open)"
    return "off — say \"morse mode\" to start"


def _finite(value: object, default: float) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return default
    return number if math.isfinite(number) and number >= 0 else default


@dataclass(frozen=True)
class ModeConfig:
    """Thresholds (level units) and timings (ms) for :class:`MorseMode`.

    ``entry_hum_ms = 0`` turns the hum trigger off; the mode is then entered only by
    :meth:`MorseMode.enter` (the spoken command).
    """

    on_level: float
    off_level: float
    entry_hum_ms: float = DEFAULT_ENTRY_HUM_S * 1000.0
    exit_silence_ms: float = DEFAULT_EXIT_SILENCE_S * 1000.0
    max_hum_cv: float = MAX_HUM_CV
    min_hum_samples: int = MIN_HUM_SAMPLES
    calib: MorseCalib = field(default_factory=MorseCalib)

    def __post_init__(self) -> None:
        for name in ("on_level", "off_level", "entry_hum_ms", "exit_silence_ms", "max_hum_cv"):
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be a finite number >= 0, got {value!r}")
        if self.on_level <= 0:
            # A zero threshold makes silence a hum, and every sample a pulse.
            raise ValueError(f"on_level must be > 0, got {self.on_level!r}")
        if self.off_level > self.on_level:
            raise ValueError(
                f"off_level ({self.off_level}) must not exceed on_level ({self.on_level})"
            )
        if self.min_hum_samples < 2:
            raise ValueError(f"min_hum_samples must be >= 2, got {self.min_hum_samples!r}")
        if self.exit_silence_ms <= self.calib.word_gap_ms:
            raise ValueError(
                f"exit_silence_ms ({self.exit_silence_ms}) must exceed the word gap "
                f"({self.calib.word_gap_ms}), or every space would end Morse mode"
            )

    @property
    def hum_entry(self) -> bool:
        """True when the long-hum trigger is on."""
        return self.entry_hum_ms > 0


def resolve(entry_hum_s: object, exit_silence_s: object, threshold: object, *,
            dot_max_ms: object = 200.0, letter_gap_ms: object = 600.0,
            word_gap_ms: object = 1400.0, hysteresis: float = 0.6,
            ) -> tuple[ModeConfig | None, list[str]]:
    """User config -> a valid :class:`ModeConfig` plus what was repaired, or None + why. Pure.

    Never raises. A non-numeric or negative value falls back to its default; an exit
    silence that does not outlast the word gap is raised above it. A threshold that is
    not a positive number cannot be repaired — there is no safe level to invent — so it
    returns ``None`` and the reason.
    """
    notes: list[str] = []
    level = _finite(threshold, 0.0)
    if level <= 0:
        return None, [f"the voice threshold ({threshold!r}) is not a positive number, so "
                      "there is no level to tell a hum from silence"]
    calib = MorseCalib(
        dot_max_ms=_finite(dot_max_ms, 200.0) or 200.0,
        letter_gap_ms=_finite(letter_gap_ms, 600.0) or 600.0,
        word_gap_ms=_finite(word_gap_ms, 1400.0) or 1400.0,
    )
    hum_s = _finite(entry_hum_s, -1.0)
    if hum_s < 0:
        notes.append(f"entry_hum_s = {entry_hum_s!r} is not a number >= 0; "
                     f"using {DEFAULT_ENTRY_HUM_S}")
        hum_s = DEFAULT_ENTRY_HUM_S
    exit_s = _finite(exit_silence_s, -1.0)
    if exit_s < 0:
        notes.append(f"exit_silence_s = {exit_silence_s!r} is not a number >= 0; "
                     f"using {DEFAULT_EXIT_SILENCE_S}")
        exit_s = DEFAULT_EXIT_SILENCE_S
    exit_ms = exit_s * 1000.0
    if exit_ms <= calib.word_gap_ms:
        raised = calib.word_gap_ms + _EXIT_MARGIN_MS
        notes.append(f"exit_silence_s = {exit_s} does not outlast the word gap "
                     f"({calib.word_gap_ms / 1000.0:g} s); using {raised / 1000.0:g} s")
        exit_ms = raised
    return ModeConfig(
        on_level=level, off_level=level * hysteresis, entry_hum_ms=hum_s * 1000.0,
        exit_silence_ms=exit_ms, calib=calib,
    ), notes


class HumDetector:
    """Fires once on a long, steady, unbroken tone; never on speech-shaped levels. Pure state.

    See the module docstring for the three conditions. After firing it will not fire again
    until the level has dropped below ``on_level`` at least once, so one continuous sound —
    a hum held on, or a steady fan above the threshold — can fire at most once.
    """

    def __init__(self, config: ModeConfig) -> None:
        self._cfg = config
        self._run_start: float | None = None
        self._window: deque[tuple[float, float]] = deque()
        self._last_t: float | None = None
        self._need_quiet = False

    @property
    def in_run(self) -> bool:
        return self._run_start is not None

    def reset(self, *, need_quiet: bool = False) -> None:
        """Forget the current run. ``need_quiet``: also refuse a new one until a quiet sample."""
        self._run_start = None
        self._window.clear()
        if need_quiet:
            self._need_quiet = True

    def push(self, t_ms: float, level: float) -> bool:
        """Feed one sample; True exactly when it completes an entry hum."""
        if not math.isfinite(t_ms) or (self._last_t is not None and t_ms < self._last_t):
            return False
        self._last_t = t_ms
        if not math.isfinite(level):
            level = 0.0
        cfg = self._cfg
        floor = cfg.off_level if self._run_start is not None else cfg.on_level
        if level < floor:
            self.reset()  # rule 1: one drop restarts the run
            self._need_quiet = False
            return False
        if self._need_quiet:
            return False  # the sound that last fired (or ended the mode) has not stopped yet
        if self._run_start is None:
            self._run_start = t_ms
        window = self._window
        window.append((t_ms, level))
        while window and window[0][0] < t_ms - cfg.entry_hum_ms:
            window.popleft()
        if t_ms - self._run_start < cfg.entry_hum_ms or len(window) < cfg.min_hum_samples:
            return False
        if not _steady([lv for _, lv in window], cfg.max_hum_cv):
            return False  # rule 2: an unsteady run slides on; a steady stretch may still come
        self.reset(need_quiet=True)
        return True


def _steady(levels: list[float], max_cv: float) -> bool:
    mean = sum(levels) / len(levels)
    if mean <= 0:
        return False
    var = sum((lv - mean) ** 2 for lv in levels) / len(levels)
    return math.sqrt(var) / mean <= max_cv


@dataclass(frozen=True)
class ModeStep:
    """What one sample (or one explicit call) did: text to type, and any mode change."""

    text: str = ""
    #: ``"hum"`` or ``"command"`` when this step entered the mode, else None.
    entered: str | None = None
    #: Why this step left the mode (``"silence"``, ``"prosign"``, ``"dictation"``,
    #: ``"paused"``, ``"no_release"``, ``"stopped"``), else None.
    exited: str | None = None


class MorseMode:
    """idle <-> armed -> morse -> idle, over a ``(t_ms, level)`` stream. Pure state.

    ``busy=True`` on :meth:`push` means the daemon is doing something else with the
    microphone (a hold-to-talk recording): an idle mode stops listening for the hum, and
    an active one ends with reason ``"dictation"`` — the user reached for the other input.
    """

    def __init__(self, config: ModeConfig, *, adapt: bool = True) -> None:
        self._cfg = config
        self._adapt = adapt
        self._hum = HumDetector(config)
        self._state = IDLE
        self._entered_by: str | None = None
        self._armed_at = 0.0
        self._last_t: float | None = None
        self._seg: PulseSegmenter | None = None
        self._stream: MorseStream | None = None
        self._last_activity = 0.0

    @property
    def config(self) -> ModeConfig:
        return self._cfg

    @property
    def state(self) -> str:
        return self._state

    @property
    def active(self) -> bool:
        """True from the moment entry was accepted until the mode ends (armed or morse)."""
        return self._state != IDLE

    @property
    def entered_by(self) -> str | None:
        return self._entered_by if self.active else None

    def enter(self, t_ms: float, reason: str = "command") -> ModeStep:
        """Enter Morse mode now (the spoken command). No-op while already active."""
        if self.active:
            return ModeStep()
        return self._arm(t_ms if math.isfinite(t_ms) else (self._last_t or 0.0), reason)

    def exit(self, t_ms: float, reason: str = "stopped") -> ModeStep:
        """Leave Morse mode now, dropping any half-keyed letter. No-op while idle."""
        if not self.active:
            return ModeStep()
        self._leave()
        return ModeStep(exited=reason)

    def push(self, t_ms: float, level: float, *, busy: bool = False) -> ModeStep:
        """Feed one sample; return what it did."""
        if not math.isfinite(t_ms) or (self._last_t is not None and t_ms < self._last_t):
            return ModeStep()
        self._last_t = t_ms
        if not math.isfinite(level):
            level = 0.0
        cfg = self._cfg

        if busy:
            self._hum.reset()
            if self.active:
                self._leave()
                return ModeStep(exited="dictation")
            return ModeStep()

        if self._state == IDLE:
            if cfg.hum_entry and self._hum.push(t_ms, level):
                return self._arm(t_ms, "hum")
            return ModeStep()

        if self._state == ARMED:
            if level < cfg.off_level:
                self._start_decoding(t_ms)
                return ModeStep()
            if t_ms - self._armed_at >= ARMED_TIMEOUT_MS:
                self._leave()
                return ModeStep(exited="no_release")
            return ModeStep()

        # MORSE
        stream, seg = self._stream, self._seg
        assert stream is not None and seg is not None
        text = stream.push(t_ms, level)
        if stream.take_prosign() == "SK":
            # End of work: SK itself typed nothing; letters before it were typed already.
            self._leave()
            return ModeStep(text=text, exited="prosign")
        if seg.in_pulse:
            self._last_activity = t_ms
        if not seg.in_pulse and t_ms - self._last_activity >= cfg.exit_silence_ms:
            text += stream.flush(t_ms)
            reason = "prosign" if stream.take_prosign() == "SK" else "silence"
            self._leave()
            return ModeStep(text=text, exited=reason)
        return ModeStep(text=text)

    # ---- internals ---------------------------------------------------------

    def _arm(self, t_ms: float, reason: str) -> ModeStep:
        self._hum.reset()
        self._state = ARMED
        self._entered_by = reason
        self._armed_at = t_ms
        return ModeStep(entered=reason)

    def _start_decoding(self, t_ms: float) -> None:
        cfg = self._cfg
        self._seg = PulseSegmenter(SegmenterConfig(on_level=cfg.on_level, off_level=cfg.off_level))
        self._stream = MorseStream(self._seg, cfg.calib, adapt=self._adapt)
        self._last_activity = t_ms
        self._state = MORSE

    def _leave(self) -> None:
        self._state = IDLE
        self._entered_by = None
        self._seg = None
        self._stream = None
        # A sound still going when the mode ends (a dash, a fan that never let it start)
        # must stop before it can count as a new entry hum.
        self._hum.reset(need_quiet=True)
