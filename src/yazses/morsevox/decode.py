"""Vocal-Morse timing classifier + decoder + adaptive calibration (pure) — ADR-v2-105.

Classify pulse/gap durations into Morse tokens, decode them to text, and re-fit the dot/dash
threshold to the user's rhythm. Pure and deterministic; pulse timing is supplied upstream.

**Prosigns.** A prosign is a procedural signal keyed as ONE character: its letters run
together with only symbol gaps between them, no letter gap. This decoder already splits
characters on timing alone (a letter ends at a silence of ``letter_gap_ms``), so a prosign
needs no special segmentation: it arrives as one longer code between two letter gaps.
The only one recognised is **SK** (``...-.-``, end of work), which ends Morse mode. The
rule, so it never swallows ordinary letters:

* SK is matched only as a *whole* character: exactly the six symbols ``...-.-`` with a
  letter gap (or a word gap, or the start of the mode) on each side.
* "S" and "K" keyed with a normal letter gap between them are two characters, ``...``
  and ``-.-``, and decode to the letters ``"sk"`` as before.
* A longer run that merely starts with ``...-.-`` is a different, unknown code and is
  dropped like any other unknown code.
* SK is never typed, and no space follows it. Letters decoded before it were already
  emitted at their own letter gaps, so in the middle of a word ("ab", then SK) the "ab"
  stays typed and the mode ends; nothing keyed after SK is decoded.
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

#: The end-of-work prosign SK, keyed as one character (no letter gap between S and K).
SK = "...-.-"
#: Prosign code -> its name. Disjoint from :data:`_MORSE`, so no letter is shadowed.
PROSIGNS = {SK: "SK"}


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
    """Accumulate dot/dash tokens and emit decoded characters at letter/word gaps. Pure state.

    A prosign (see the module docstring) closed by a gap returns ``None`` (nothing to type,
    not even the word gap's space) and is reported once through :meth:`take_prosign`.
    """

    def __init__(self) -> None:
        self._buf = ""
        self._prosign: str | None = None

    def feed(self, symbol: str):
        """Feed a token (``dot``/``dash``/``gap_letter``/``gap_word``); return a char/word or None. Pure state."""
        if symbol == "dot":
            self._buf += "."
            return None
        if symbol == "dash":
            self._buf += "-"
            return None
        if symbol in ("gap_letter", "gap_word"):
            code, self._buf = self._buf, ""
            prosign = PROSIGNS.get(code) if code else None
            if prosign is not None:
                self._prosign = prosign
                return None
            char = _MORSE.get(code, "") if code else ""
            if symbol == "gap_word":
                return char + " "
            return char or None
        return None

    def take_prosign(self) -> str | None:
        """The prosign (``"SK"``) the last gap closed, once; then None until another."""
        prosign, self._prosign = self._prosign, None
        return prosign


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
