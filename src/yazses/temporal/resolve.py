"""Relative-date resolution (pure) — ADR-v2-057.

Replace spoken relative-date expressions with concrete formatted dates, resolved against an
injected ``now`` (so the function is pure and deterministically testable). Stdlib datetime only.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4,
    "saturday": 5, "sunday": 6,
}
_WD_ALT = "|".join(_WEEKDAYS)


def _fmt(d: datetime) -> str:
    """Format a date as e.g. 'Fri Jul 10 2026' (no zero-padded day). Pure."""
    return f"{d:%a %b} {d.day} {d:%Y}"


def resolve_temporal(text: str, now: datetime) -> str:
    """Replace relative-date expressions in ``text`` with concrete dates. Pure.

    Handles today/tomorrow/yesterday, this/next <weekday>, and "in N days/weeks".
    """
    if not text:
        return text

    def next_wd(m: re.Match) -> str:
        wd = _WEEKDAYS[m.group(1).lower()]
        days = (wd - now.weekday()) % 7 or 7      # strictly the upcoming one
        return _fmt(now + timedelta(days=days))

    def this_wd(m: re.Match) -> str:
        wd = _WEEKDAYS[m.group(1).lower()]
        return _fmt(now + timedelta(days=(wd - now.weekday()) % 7))

    def in_days(m: re.Match) -> str:
        return _fmt(now + timedelta(days=int(m.group(1))))

    def in_weeks(m: re.Match) -> str:
        return _fmt(now + timedelta(weeks=int(m.group(1))))

    out = re.sub(rf"\bnext ({_WD_ALT})\b", next_wd, text, flags=re.IGNORECASE)
    out = re.sub(rf"\bthis ({_WD_ALT})\b", this_wd, out, flags=re.IGNORECASE)
    out = re.sub(r"\bin (\d+) days?\b", in_days, out, flags=re.IGNORECASE)
    out = re.sub(r"\bin (\d+) weeks?\b", in_weeks, out, flags=re.IGNORECASE)
    out = re.sub(r"\btomorrow\b", _fmt(now + timedelta(days=1)), out, flags=re.IGNORECASE)
    out = re.sub(r"\byesterday\b", _fmt(now - timedelta(days=1)), out, flags=re.IGNORECASE)
    out = re.sub(r"\btoday\b", _fmt(now), out, flags=re.IGNORECASE)
    return out
