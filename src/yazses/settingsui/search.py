"""Filtering the settings window's ~200 rows. Pure — no Qt, no I/O.

`yazses features` has had `--on`, `--tier` and `--category` since it was written,
because a flat list of two hundred capabilities is not browsable. The window
shipped without any of it, so the only way to find a row was to scroll past every
other one — which is also the reason its per-row help went unread: you have to
reach a row before it can explain itself.

One box, matched against everything a person might type: the name they can see,
the slug the CLI uses, the category heading, and the description and use-case
text — so "stutter" finds Dysfluency-Friendly, whose label contains neither word.

Two filter tokens mirror the CLI flags rather than inventing a second vocabulary:
``on:`` / ``off:`` and ``tier:``. Anything else is plain substring text.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence

# Tier words a user might type, mapped onto the substring that identifies the
# tier in `Feature.tier_label`. Keys are what `yazses features --tier` accepts,
# so the two surfaces take the same words.
_TIER_ALIASES: dict[str, str] = {
    "core": "core",
    "on": "on by default",
    "default": "on by default",
    "rec": "recommended",
    "recommended": "recommended",
    "opt": "optional",
    "optional": "optional",
    "exp": "experimental",
    "experimental": "experimental",
    "planned": "planned",
}


def parse_query(query: str) -> tuple[tuple[str, ...], bool | None, str | None]:
    """Split *query* into ``(text_terms, enabled_filter, tier_filter)``.

    Unknown ``foo:`` tokens are kept as plain text rather than silently dropped:
    a typo'd filter that quietly matches everything is worse than one that
    matches nothing, because the user cannot see it happen.
    """
    terms: list[str] = []
    enabled: bool | None = None
    tier: str | None = None
    for token in (query or "").split():
        lowered = token.lower()
        if lowered in ("on:", "on:true", "is:on", "enabled:"):
            enabled = True
        elif lowered in ("off:", "on:false", "is:off", "disabled:"):
            enabled = False
        elif lowered.startswith("tier:") and lowered[5:] in _TIER_ALIASES:
            tier = _TIER_ALIASES[lowered[5:]]
        else:
            terms.append(lowered)
    return tuple(terms), enabled, tier


def matches(row, query: str, *, category: str = "") -> bool:
    """Whether *row* should stay visible for *query*.

    Every term must match somewhere (AND, not OR): typing two words narrows,
    which is what a filter box is for.
    """
    terms, enabled, tier = parse_query(query)
    if enabled is not None and bool(row.enabled) is not enabled:
        return False
    if tier is not None and tier not in (row.tier_label or "").lower():
        return False
    if not terms:
        return True
    haystack = _haystack(row, category)
    return all(term in haystack for term in terms)


def visible_counts(groups: Iterable, query: str) -> tuple[int, int]:
    """``(matching, total)`` rows across *groups*, for the "showing N of M" line."""
    matching = total = 0
    for group in groups:
        for row in group.rows:
            total += 1
            if matches(row, query, category=group.category):
                matching += 1
    return matching, total


def describe_filter(matching: int, total: int, query: str) -> str:
    """The status line under the filter box.

    Says nothing when nothing is filtered — an unconditional "showing 200 of 200"
    is noise that trains people to stop reading the line that matters.
    """
    if not (query or "").strip():
        return ""
    if matching == 0:
        return f"No capability matches {query.strip()!r}. Try a shorter word."
    return f"Showing {matching} of {total} capabilities."


def _haystack(row, category: str) -> str:
    """Everything a user might reasonably type to find this row, lower-cased."""
    parts: Sequence[str] = (
        row.slug or "",
        row.label or "",
        category or "",
        row.tier_label or "",
        row.why or "",
        getattr(row, "use_case", "") or "",
        getattr(row, "example", "") or "",
        getattr(row, "note", "") or "",
    )
    return " ".join(parts).lower()
