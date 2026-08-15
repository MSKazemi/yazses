"""Decide whether a dictated utterance is a checkable number that failed (pure).

`validate.py` answers "does this string pass Luhn/ISBN/Verhoeff". This answers the
question the daemon actually has: **is this utterance a number worth checking, and if
so, is it wrong?**

The distinction matters because the second question is where a guard like this succeeds
or fails as a feature. ADR-021's rule is that a confirmation is judged on how *rarely*
it fires: a guard that interrupts a house number or a year teaches the user to dismiss
it, and a dismissed guard is worse than no guard, because it costs attention and catches
nothing. So the gate here is deliberately narrow:

* the utterance must be **essentially all digits** — a sentence containing a number is
  prose, and prose is not being entered into a card field;
* it must be **long enough** that a checksum means something (`min_digits`);
* it must **fail every configured scheme whose length it fits**. A 13-digit number is not
  an ISBN-10, so ISBN-10's opinion of it is noise, not evidence.

Everything else types with no comment.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from yazses.checkdigit.validate import suggest_fix, validate

#: Length each scheme is defined for. `None` means "any length" (Luhn and Verhoeff are
#: defined over any digit string). A scheme is only consulted when the length fits, so a
#: 16-digit card is never judged by ISBN-13's arithmetic.
_SCHEME_LENGTHS: dict[str, int | None] = {
    "luhn": None,
    "verhoeff": None,
    "isbn13": 13,
    "isbn10": 10,
}

#: Separators people say or that ITN inserts inside a spoken number. Anything else
#: present in quantity means this is prose.
_SEPARATORS = re.compile(r"[\s\-.]")


@dataclass(frozen=True)
class CheckResult:
    """Whether to hold *text*, and what to say about it."""

    #: True when the utterance is a checkable number that failed its checksum.
    failed: bool
    #: The scheme it failed under, for the message. Empty when nothing was checked.
    scheme: str = ""
    #: The digits as checked, separators removed.
    digits: str = ""
    #: The single-digit correction, when exactly one candidate passes.
    suggestion: str = ""

    @property
    def checked(self) -> bool:
        """Whether any scheme was applicable at all."""
        return bool(self.scheme)


def _digits_only(text: str) -> str:
    return _SEPARATORS.sub("", (text or "").strip())


def looks_like_a_number(text: str, min_digits: int) -> bool:
    """Whether *text* is a bare number long enough to be worth checking. Pure.

    "4539 1488 0343 6467" qualifies. "my card is 4539..." does not — that is prose, and
    a user dictating a sentence is not filling a payment field. The check is intentionally
    strict in that direction: a missed catch costs one wrong digit, and a false catch
    costs the user's trust in every future prompt.
    """
    stripped = _digits_only(text)
    if len(stripped) < max(1, min_digits):
        return False
    # ISBN-10 may legitimately end in a check character 'X'.
    body = stripped[:-1] if stripped[-1:].upper() == "X" else stripped
    return body.isdigit()


def check(
    text: str,
    schemes: Sequence[str] | None = None,
    *,
    min_digits: int = 12,
    want_suggestion: bool = True,
) -> CheckResult:
    """Check *text* against each applicable scheme. Pure.

    Returns ``failed=False`` when the utterance is not a number worth checking, when no
    configured scheme fits its length, or when **any** applicable scheme passes. That last
    one is deliberate: a string that satisfies a real checksum is overwhelmingly likely to
    be that kind of number, and holding it because a *different* scheme disagrees would be
    the guard inventing a problem.
    """
    if not looks_like_a_number(text, min_digits):
        return CheckResult(failed=False)

    digits = _digits_only(text)
    applicable = [
        s for s in (schemes or ("luhn",))
        if s in _SCHEME_LENGTHS
        and (_SCHEME_LENGTHS[s] is None or _SCHEME_LENGTHS[s] == len(digits))
    ]
    if not applicable:
        return CheckResult(failed=False)

    for scheme in applicable:
        try:
            ok, normalised = validate(digits, scheme)
        except ValueError:  # pragma: no cover - filtered by _SCHEME_LENGTHS above
            continue
        if ok:
            return CheckResult(failed=False, scheme=scheme, digits=normalised)

    # Every applicable scheme rejected it. Report the first, which is the most specific
    # the user configured.
    scheme = applicable[0]
    suggestion = ""
    if want_suggestion:
        candidates = suggest_fix(digits, scheme)
        if len(candidates) == 1:
            suggestion = candidates[0]
    return CheckResult(failed=True, scheme=scheme, digits=digits, suggestion=suggestion)


def describe(result: CheckResult) -> str:
    """The one-line message for a failed check. Empty when nothing failed."""
    if not result.failed:
        return ""
    name = {"luhn": "checksum", "isbn13": "ISBN-13", "isbn10": "ISBN-10",
            "verhoeff": "checksum"}.get(result.scheme, result.scheme)
    if result.suggestion:
        return (
            f"That number fails its {name} — did you mean {result.suggestion}? "
            f"Say it again, or say “confirm” to type it as heard."
        )
    return (
        f"That number fails its {name}, so a digit was probably misheard. "
        f"Say it again, or say “confirm” to type it as heard."
    )
