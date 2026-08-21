"""What each settings row *means*, as text. Pure — no Qt, no I/O.

A checkbox and a tier label answer "is it on?", never "what will this do to my
dictation, when would I want it, and what does ticking it actually change?".
That gap is why a switchboard of ~200 capabilities is unusable without help
text: the label alone is a guess.

The answer already exists. The registry carries a description, a "use when"
scenario, a concrete example, the exact config keys the toggle writes, and any
packages it pulls in — that is what ``yazses features info`` prints. This module
renders the *same* material for the window, so the two surfaces can never
describe a capability differently.

One source, three renderings, because one is never enough:

* :func:`summary_line` — the line under the checkbox. Always visible, so it must
  stay short; ~200 paragraphs is a wall, not documentation.
* :func:`help_html` — the hover tooltip and the "?" details dialog, as Qt rich
  text (a small HTML subset that renders identically on X11, Wayland and
  Windows — no CSS, no web engine, nothing that varies by Qt build).
* :func:`help_text` — the same content in plain text, for the accessible
  description a screen reader announces and for anywhere HTML would leak. A
  tooltip no screen reader reads is not help for the users this project exists
  for, and hover is not reachable by keyboard at all — which is why the "?"
  button exists beside it rather than instead of it.
"""
from __future__ import annotations

import html
from collections.abc import Mapping, Sequence

# Longer than this and the always-visible summary stops being scannable. Full
# text is one hover or one "?" click away, so nothing is lost by cutting here.
SUMMARY_MAX = 110

# Section headings, in display order. Named so the copy lives in one place and
# the tests can assert on it.
H_WHAT = "What it does"
H_WHEN = "Use when"
H_EXAMPLE = "Example"
H_CHANGES = "Turning it on"
H_NEEDS = "Also installs"
H_DEFAULT = "Out of the box"
H_STATUS = "Status"


def summary_line(row) -> str:
    """The one-line description shown under a row's checkbox.

    Tier first — "is this advised?" is the question a scanning eye asks — then
    as much of the description as fits on a line.
    """
    lead = row.tier_label
    detail = _first_sentence(row.why)
    if not detail:
        return lead
    return f"{lead} — {_truncate(detail, SUMMARY_MAX)}"


def help_sections(row) -> tuple[tuple[str, str], ...]:
    """``(heading, body)`` pairs describing *row*, in display order.

    The single place that decides *what* is said about a capability;
    :func:`help_html` and :func:`help_text` only decide how it looks. Empty
    sections are dropped, so a sparsely-documented capability shows a short card
    rather than a scaffold of blank headings.
    """
    sections: list[tuple[str, str]] = [
        (H_WHAT, (row.why or "").strip()),
        (H_WHEN, (getattr(row, "use_case", "") or "").strip()),
        (H_EXAMPLE, (getattr(row, "example", "") or "").strip()),
        (H_CHANGES, _changes(row)),
        (H_NEEDS, _packages(row)),
        (H_DEFAULT, _default(row)),
        (H_STATUS, (row.tier_label or "").strip()),
    ]
    return tuple((head, body) for head, body in sections if body)


def help_text(row) -> str:
    """Plain-text help — the screen-reader description and the CLI-shaped form."""
    parts = [row.label]
    parts += [f"{head}: {body}" for head, body in help_sections(row)]
    return "\n".join(parts)


def help_html(row) -> str:
    """Qt rich text for the tooltip and the details dialog.

    Deliberately boring HTML — ``<b>``, ``<br>``, ``<p>`` and nothing else. Qt's
    tooltip renderer supports a subset of HTML 4 that has been stable since Qt 4,
    which is what makes this identical on an Ubuntu LTS from several years ago
    and on Windows. Every value is escaped: capability text is full of ``<file>``
    placeholders and ``&`` that would otherwise be eaten as markup.
    """
    body = "".join(
        f"<p><b>{html.escape(head)}</b><br>{_escape_multiline(text)}</p>"
        for head, text in help_sections(row)
    )
    return f"<p><b>{html.escape(row.label)}</b></p>{body}"


def accessible_description(row) -> str:
    """What a screen reader should announce for the row, as one string."""
    return help_text(row).replace("\n", ". ")


def reset_message(diff: Sequence[tuple[str, bool]], labels: Mapping[str, str]) -> str:
    """The confirmation body for "Restore defaults" — names every row it touches.

    A reset dialog that says only "restore defaults?" asks the user to approve a
    change they cannot see. This lists it: what goes on, what goes off, by name.
    """
    if not diff:
        return "Every capability is already at its default. Nothing to restore."
    turning_on = [labels.get(slug, slug) for slug, desired in diff if desired]
    turning_off = [labels.get(slug, slug) for slug, desired in diff if not desired]
    lines: list[str] = []
    if turning_on:
        lines.append(f"Turn ON ({len(turning_on)}):  " + ", ".join(sorted(turning_on)))
    if turning_off:
        lines.append(f"Turn OFF ({len(turning_off)}):  " + ", ".join(sorted(turning_off)))
    lines.append(
        "\nNothing is written until you click Apply, and your hotkey, microphone, "
        "vocabulary and any hand-edited settings are left alone."
    )
    return "\n".join(lines)


# --- section bodies ---------------------------------------------------------


def _changes(row) -> str:
    """What ticking the box writes — the concrete answer, not a reassurance.

    Naming the exact keys is the point: it is what makes the window auditable
    against the config file the user may also be editing by hand.
    """
    if not row.toggleable:
        return ""
    writes = getattr(row, "on_writes", ()) or ()
    if not writes:
        return ""
    keys = ", ".join(f"[{section}] {key} = {value}" for section, key, value, _q in writes)
    return f"Writes {keys} to your config file. Takes effect after a restart."


def _packages(row) -> str:
    packages = tuple(getattr(row, "packages", ()) or ())
    if not packages:
        return ""
    return (
        f"{' '.join(packages)} — downloaded the first time you enable it. "
        "Everything still runs on your machine."
    )


def _default(row) -> str:
    if not row.toggleable:
        if not getattr(row, "wired", True):
            return (
                "Designed but not wired into this build yet — the switch would "
                "write a config key nothing reads, so it is shown, not offered."
            )
        return "Always on. Part of the pipeline itself, not a switch."
    default = getattr(row, "default_enabled", None)
    if default is None:
        return ""
    return "On by default." if default else "Off by default."


# --- text helpers -----------------------------------------------------------


def _first_sentence(text: str) -> str:
    """The lead sentence of *text*, for the always-visible summary.

    Splits on ". " rather than "." so a decimal, an ellipsis or a config key like
    ``small.en`` cannot cut the sentence in half — and skips a split that lands
    straight after an abbreviation, because the registry is full of "(e.g. a
    USB-C monitor stealing capture)" and stopping at "(e.g." reads as a bug.
    """
    cleaned = " ".join((text or "").split())
    start = 0
    while True:
        cut = cleaned.find(". ", start)
        if cut < 0:
            return cleaned
        head = cleaned[:cut]
        if not _ends_in_abbreviation(head):
            return head + "."
        start = cut + 2


def _ends_in_abbreviation(head: str) -> bool:
    """Whether *head* ends mid-abbreviation, so the next ". " is not a sentence end."""
    last = head.rsplit(" ", 1)[-1].lstrip("([\"'")
    return last.lower() in _ABBREVIATIONS


# Abbreviations that end in a dot and are followed by more of the same sentence.
# The trailing dot is not included: it is the "." of the ". " being tested.
_ABBREVIATIONS = frozenset({
    "e.g", "i.e", "etc", "vs", "cf", "approx", "incl", "no", "ca", "al",
})


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip(" ,;:.") + "…"


def _escape_multiline(text: str) -> str:
    return "<br>".join(html.escape(line) for line in text.splitlines())
