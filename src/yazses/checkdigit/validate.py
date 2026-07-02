"""Check-digit validation + single-edit fix suggestion (pure) — ADR-v2-106.

Validate digits against Luhn / ISBN-10 / ISBN-13 / Verhoeff and propose single-digit corrections.
Pure integer arithmetic; no dependency.
"""
from __future__ import annotations

import re

_SCHEMES = ("luhn", "isbn10", "isbn13", "verhoeff")

# Verhoeff tables (dihedral group D5).
_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6], [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4], [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]
_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2], [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]


def _normalize(digits: str, scheme: str) -> str:
    s = re.sub(r"[\s\-]", "", digits or "").upper()
    if scheme == "isbn10":
        return s                     # may end in 'X'
    return re.sub(r"[^0-9]", "", s)


def _luhn_ok(d: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(d)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return len(d) > 0 and total % 10 == 0


def _isbn13_ok(d: str) -> bool:
    if len(d) != 13:
        return False
    total = sum(int(ch) * (1 if i % 2 == 0 else 3) for i, ch in enumerate(d))
    return total % 10 == 0


def _isbn10_ok(d: str) -> bool:
    if len(d) != 10:
        return False
    total = 0
    for i, ch in enumerate(d):
        val = 10 if ch == "X" else (int(ch) if ch.isdigit() else -1)
        if val < 0:
            return False
        total += (10 - i) * val
    return total % 11 == 0


def _verhoeff_ok(d: str) -> bool:
    if not d.isdigit() or not d:
        return False
    c = 0
    for i, ch in enumerate(reversed(d)):
        c = _D[c][_P[i % 8][int(ch)]]
    return c == 0


_VALIDATORS = {"luhn": _luhn_ok, "isbn10": _isbn10_ok, "isbn13": _isbn13_ok, "verhoeff": _verhoeff_ok}


def validate(digits: str, scheme: str):
    """Validate ``digits`` under ``scheme`` → ``(ok, normalized)``. Unknown scheme → ValueError. Pure."""
    if scheme not in _VALIDATORS:
        raise ValueError(f"unknown scheme: {scheme}")
    norm = _normalize(digits, scheme)
    return (_VALIDATORS[scheme](norm), norm)


def suggest_fix(digits: str, scheme: str):
    """Return sorted single-digit-edit variants of ``digits`` that pass ``scheme``. Pure."""
    norm = _normalize(digits, scheme)
    out = set()
    for i in range(len(norm)):
        if not norm[i].isdigit():
            continue
        for d in "0123456789":
            if d == norm[i]:
                continue
            cand = norm[:i] + d + norm[i + 1:]
            if _VALIDATORS[scheme](cand):
                out.add(cand)
    return sorted(out)
