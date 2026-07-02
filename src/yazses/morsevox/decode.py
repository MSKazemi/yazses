"""Vocal-Morse timing classifier + decoder + adaptive calibration (pure) — ADR-v2-105.

Classify pulse/gap durations into Morse tokens, decode them to text, and re-fit the dot/dash
threshold to the user's rhythm. Pure and deterministic; pulse timing is supplied upstream.
"""
from __future__ import annotations

from dataclasses import dataclass

_MORSE = {
    ".-": "a", "-...": "b", "-.-.": "c", "-..": "d", ".": "e", "..-.": "f",
    "--.": "g", "....": "h", "..": "i", ".---": "j", "-.-": "k", ".-..": "l",
    "--": "m", "-.": "n", "---": "o", ".--.": "p", "--.-": "q", ".-.": "r",
    "...": "s", "-": "t", "..-": "u", "...-": "v", ".--": "w", "-..-": "x",
    "-.--": "y", "--..": "z",
    "-----": "0", ".----": "1", "..---": "2", "...--": "3", "....-": "4",
    ".....": "5", "-....": "6", "--...": "7", "---..": "8", "----.": "9",
}


@dataclass(frozen=True)
class MorseCalib:
    """Timing thresholds (ms): pulse ≤ ``dot_max_ms`` is a dot; gaps split letters/words."""
    dot_max_ms: float = 200.0
    letter_gap_ms: float = 600.0
    word_gap_ms: float = 1400.0


def classify_pulse(duration_ms: float, calib: MorseCalib) -> str:
    """A vocal pulse → ``dot`` (short) or ``dash`` (long). Pure."""
    return "dot" if duration_ms <= calib.dot_max_ms else "dash"


def classify_gap(silence_ms: float, calib: MorseCalib) -> str:
    """A silence → ``gap_symbol`` | ``gap_letter`` | ``gap_word``. Pure."""
    if silence_ms >= calib.word_gap_ms:
        return "gap_word"
    if silence_ms >= calib.letter_gap_ms:
        return "gap_letter"
    return "gap_symbol"


class MorseDecoder:
    """Accumulate dot/dash tokens and emit decoded characters at letter/word gaps. Pure state."""

    def __init__(self) -> None:
        self._buf = ""

    def feed(self, symbol: str):
        """Feed a token (``dot``/``dash``/``gap_letter``/``gap_word``); return a char/word or None. Pure state."""
        if symbol == "dot":
            self._buf += "."
            return None
        if symbol == "dash":
            self._buf += "-"
            return None
        if symbol in ("gap_letter", "gap_word"):
            char = _MORSE.get(self._buf, "") if self._buf else ""
            self._buf = ""
            if symbol == "gap_word":
                return char + " "
            return char or None
        return None


def adapt_dot_threshold(durations, calib: MorseCalib, alpha: float = 0.3) -> MorseCalib:
    """EMA-refit ``dot_max_ms`` toward the midpoint of the short/long pulse clusters. Pure."""
    vals = sorted(d for d in (durations or ()) if d > 0)
    if len(vals) < 2:
        return calib
    mid = len(vals) // 2
    short, long = vals[:mid], vals[mid:]
    if not short or not long:  # pragma: no cover - len>=2 guarantees both non-empty
        return calib
    boundary = (sum(short) / len(short) + sum(long) / len(long)) / 2.0
    new_dot = calib.dot_max_ms * (1.0 - alpha) + boundary * alpha
    return MorseCalib(dot_max_ms=new_dot, letter_gap_ms=calib.letter_gap_ms,
                      word_gap_ms=calib.word_gap_ms)
