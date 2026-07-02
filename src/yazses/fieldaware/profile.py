"""Focused-field role → format profile (pure) — ADR-v2-047.

Map an accessibility role/state to a formatting policy and apply it to dictated text. Pure and
deterministic; the role read comes from the platform accessibility layer.
"""
from __future__ import annotations

from dataclasses import dataclass

_PASSWORD = ("password", "passwordtext")
_NUMBER = ("spinbutton", "spin button", "number")
_SEARCH = ("search", "searchbox", "searchfield")


@dataclass(frozen=True)
class FormatProfile:
    """How to shape dictated text for a target field."""
    capitalize: bool = True
    trailing_punct: bool = True
    digits_only: bool = False
    refuse: bool = False       # never inject (e.g. a password field)


def profile_for_role(role, states=()) -> FormatProfile:
    """Map an accessibility role (+ optional state tokens) to a :class:`FormatProfile`. Pure."""
    r = (role or "").lower()
    st = {str(s).lower() for s in states}
    if any(p in r for p in _PASSWORD) or "password" in st:
        return FormatProfile(refuse=True)
    if any(n in r for n in _NUMBER) or "number" in st:
        return FormatProfile(capitalize=False, trailing_punct=False, digits_only=True)
    if any(s in r for s in _SEARCH):
        return FormatProfile(trailing_punct=False)
    return FormatProfile()


def apply_profile(text: str, profile: FormatProfile):
    """Apply ``profile`` to ``text``. Returns the shaped text, or ``None`` to refuse. Pure."""
    if profile.refuse:
        return None
    if not text:
        return text
    if profile.digits_only:
        return "".join(ch for ch in text if ch.isdigit())
    out = text
    if not profile.trailing_punct:
        out = out.rstrip()
        while out and out[-1] in ".!?,;:":
            out = out[:-1].rstrip()
    if profile.capitalize and out:
        out = out[0].upper() + out[1:]
    return out
