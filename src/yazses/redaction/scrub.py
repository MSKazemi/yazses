"""Structured PII/secret detection + masking (pure) — ADR-v2-046.

Dependency-free detectors (regex + Luhn checksum) for the highest-risk structured secrets, run
on the injection path so a spoken card number / SSN / key never lands in the wrong window.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_PHONE = re.compile(r"\b(?:\+?\d[\s-]?){9,14}\d\b")
# Common secret-key shapes: OpenAI sk-, AWS AKIA, GitHub ghp_/gho_, generic long hex.
_KEY = re.compile(r"\b(?:sk-[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{12,}|gh[po]_[A-Za-z0-9]{16,})\b")
# Candidate card: 13-19 digits allowing single spaces/dashes between groups.
_CARD_CAND = re.compile(r"\b(?:\d[ -]?){13,19}\b")


@dataclass(frozen=True)
class RedactionResult:
    """Masked text plus the categories that were found."""
    text: str
    redactions: list


def _luhn(digits: str) -> bool:
    """Luhn checksum over a pure digit string. Pure."""
    if len(digits) < 13:
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = ord(ch) - 48
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def redact(text: str, mode: str = "mask") -> RedactionResult:
    """Detect structured secrets and mask them (or just report them). Pure.

    ``mode="mask"`` replaces each hit with ``[CATEGORY]``; any other mode leaves the text intact
    and only reports the categories found (for a hold-and-confirm flow).
    """
    found: list = []
    out = text or ""

    def sub(pattern, tag, s):
        def repl(_m):
            if tag not in found:
                found.append(tag)
            return f"[{tag}]"
        return pattern.sub(repl, s)

    # Cards first (validate Luhn on the digits only).
    def card_repl(m):
        digits = re.sub(r"\D", "", m.group(0))
        if _luhn(digits):
            if "CARD" not in found:
                found.append("CARD")
            return "[CARD]"
        return m.group(0)

    out = _CARD_CAND.sub(card_repl, out)
    out = sub(_KEY, "KEY", out)
    out = sub(_SSN, "SSN", out)
    out = sub(_EMAIL, "EMAIL", out)
    out = sub(_IPV4, "IP", out)
    out = sub(_PHONE, "PHONE", out)

    if mode == "mask":
        return RedactionResult(text=out, redactions=found)
    # non-mask ("hold"): report categories but return the original text untouched
    return RedactionResult(text=text or "", redactions=found)
