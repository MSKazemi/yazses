"""Voice-timer duration parsing + command grammar (pure) — ADR-v2-093.

Turn "set a timer for 25 minutes" into seconds and a command tuple. Pure and deterministic; the
daemon schedules the alert and the TTS speaks it.
"""
from __future__ import annotations

import re

_UNIT_SECONDS = {
    "second": 1, "seconds": 1, "sec": 1, "secs": 1,
    "minute": 60, "minutes": 60, "min": 60, "mins": 60,
    "hour": 3600, "hours": 3600, "hr": 3600, "hrs": 3600,
}
_NUM_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "fifteen": 15,
    "twenty": 20, "thirty": 30, "forty": 40, "forty-five": 45, "sixty": 60,
    "half": 0.5, "quarter": 0.25,
}
_QUANTITY = r"\d+(?:\.\d+)?|a|an|one|two|three|four|five|six|seven|eight|nine|ten|fifteen|twenty|thirty|forty|forty-five|sixty|half|quarter"
_TERM = re.compile(rf"({_QUANTITY})\s+(?:of\s+)?(?:an?\s+)?(seconds?|secs?|minutes?|mins?|hours?|hrs?)",
                   re.IGNORECASE)


def _quantity(token: str) -> float:
    token = token.lower()
    if token in _NUM_WORDS:
        return _NUM_WORDS[token]
    return float(token)


def parse_duration(text: str):
    """Parse a spoken duration into whole seconds, or ``None``. Pure.

    Handles "25 minutes", "2 hours 30 minutes", "an hour", "half an hour".
    """
    total = 0.0
    found = False
    for m in _TERM.finditer(text or ""):
        total += _quantity(m.group(1)) * _UNIT_SECONDS[m.group(2).lower()]
        found = True
    return int(round(total)) if found else None


def format_duration(seconds: int) -> str:
    """Render seconds as a spoken-ready string ("1 hour 30 minutes"). Pure."""
    seconds = max(0, int(seconds))
    parts = []
    for label, size in (("hour", 3600), ("minute", 60), ("second", 1)):
        n, seconds = divmod(seconds, size)
        if n:
            parts.append(f"{n} {label}" + ("s" if n != 1 else ""))
    return " ".join(parts) if parts else "0 seconds"


def parse_timer_command(text: str):
    """Parse a spoken timer command → ``("set", seconds)`` / ``("cancel", None)``, or None. Pure."""
    t = (text or "").lower()
    if re.search(r"\b(cancel|stop|clear)\b.*\btimer\b", t) or re.search(r"\btimer\b.*\b(cancel|stop|off)\b", t):
        return ("cancel", None)
    if re.search(r"\b(timer|remind me|remind|break|alarm)\b", t):
        secs = parse_duration(t)
        if secs:
            return ("set", secs)
    return None
