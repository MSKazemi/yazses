"""The "never sent" validation record for Send to (ADR-031 §5, issue #637).

ADR-031 §5 refuses to take "pre-filled, never sent" from a vendor's documentation: it is
something observed, per client and per operating system, on the client version that was
tried. This module is that record and the rules it obeys:

* :data:`ROWS` is the record. One :class:`ValidationRow` per run: which target, which OS
  and desktop, which client version, which YazSes version, which opener path the hand-off
  took, the date, what was seen, who saw it and a link to the evidence. **It is empty**:
  no hand-off has yet been tried against a real Claude or Codex install. A row is added
  only from a person's real run, never from a test, a fake opener or the documentation.
* ADR-031 carries the same rows as a human-readable table between the
  ``sendto-validation`` markers; ``tests/test_sendto_validation_record.py`` fails when the
  two disagree, so neither can claim a verification the other does not.
* :func:`verification_sentence` is what ``yazses features info sendto`` says about it:
  "Not yet verified ..." with no verifying row, otherwise the client versions that were.
* :func:`submitted_targets` is §5's removal rule: a target seen to submit on open may not
  stay in :data:`yazses.sendto.targets.TARGETS` (the same test fails until it is removed).
  A removed slug moves to :data:`REMOVED_TARGETS`, so its ``submitted`` row stays valid
  as history -- and a row naming a slug in neither set (a typo such as ``claud``) is a
  defect, never silent history that would switch the removal rule off.

Pure: no I/O, no clock, no logging, no imports beyond the standard library and the pure
target table.
"""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass
from enum import Enum

from yazses.sendto.targets import TARGETS


class Outcome(Enum):
    """What a person saw after one hand-off to a real client."""

    #: The client opened a new conversation with the whole prompt in its input box, and
    #: nothing was sent until the tester pressed Enter. The only outcome that verifies.
    PREFILLED_NOT_SUBMITTED = "prefilled-not-submitted"
    #: The client sent the prompt with no action by the tester. Disqualifies the target.
    SUBMITTED = "submitted"
    #: The client opened, but the input box was empty or held only part of the prompt.
    NOT_PREFILLED = "not-prefilled"
    #: Nothing opened (no handler for the scheme, the portal refused, a chooser was shown
    #: and cancelled, ...). A result, not a verification.
    DID_NOT_OPEN = "did-not-open"


#: The opener paths the platform ``UrlOpener`` seam can take on each OS (ADR-031,
#: implementation notes): the desktop portal or its ``xdg-open`` fallback on Linux,
#: ``NSWorkspace`` or its ``open`` fallback on macOS, ``ShellExecuteW`` on Windows.
OPENERS_BY_OS: dict[str, tuple[str, ...]] = {
    "linux": ("portal", "xdg-open"),
    "macos": ("nsworkspace", "open"),
    "windows": ("shellexecute",),
}

_OS_LABEL = {"linux": "Linux", "macos": "macOS", "windows": "Windows"}

#: The column headings of ADR-031's record table, in order.
TABLE_COLUMNS: tuple[str, ...] = (
    "Target", "OS", "Environment", "Client version", "YazSes version", "Opener", "Date",
    "Outcome", "Tester", "Evidence",
)


@dataclass(frozen=True)
class ValidationRow:
    """One person's run of one hand-off against one real client."""

    target: str          # a slug of the target table at the time of the run
    os: str              # a key of OPENERS_BY_OS
    environment: str     # distribution, desktop and session, e.g. "Fedora 41, KDE 6, Wayland"
    client_version: str  # as the client's About box shows it, e.g. "Claude 1.2.3"
    yazses_version: str  # `yazses --version`
    opener: str          # the path the daemon log names for this hand-off
    date: str            # ISO 8601, the day of the run
    outcome: Outcome
    tester: str          # who ran it: a person, or "AI agent" when an agent drove it
    evidence: str        # an https link to the issue comment or record with the details

    def table_cells(self) -> tuple[str, ...]:
        """This row as the cells of ADR-031's table, in :data:`TABLE_COLUMNS` order."""
        return (
            f"`{self.target}`", self.os, self.environment, self.client_version,
            self.yazses_version, self.opener, self.date, self.outcome.value, self.tester,
            self.evidence,
        )


#: The record. Empty until a person runs a hand-off against a real client and the row is
#: added here and in ADR-031's table in the same change, followed by
#: ``uv run python scripts/gen-docs.py`` (a verified row changes ``docs/features.md``) and
#: the "nothing tried yet" sentences ``tests/test_sendto_validation_record.py`` lists.
ROWS: tuple[ValidationRow, ...] = ()

#: Slugs taken out of ``TARGETS`` because a run saw them submit on open (ADR-031 §5). A
#: ``submitted`` row for one of them stays in :data:`ROWS` as the reason; every row must
#: name a live target or one of these, exactly as written.
REMOVED_TARGETS: frozenset[str] = frozenset()


def _real_iso_date(value: str) -> bool:
    try:
        return _dt.date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _evidence_link(value: str) -> bool:
    """An ``https://`` link with a real host (``https://`` alone is not evidence)."""
    if not value.startswith("https://"):
        return False
    # Parsed by hand: importing urllib, even its parser, trips the ADR-019 egress guard.
    authority = re.split(r"[/?#]", value[len("https://"):], maxsplit=1)[0]
    host = authority.rpartition("@")[2].partition(":")[0]
    labels = host.split(".")
    return len(labels) >= 2 and all(labels)


def row_problems(
    rows: tuple[ValidationRow, ...],
    known_targets: frozenset[str],
    removed_targets: frozenset[str] = REMOVED_TARGETS,
) -> list[str]:
    """Every way *rows* falls short of a usable record; an empty list means none.

    A row must name, exactly, a target in *known_targets* or in *removed_targets* (a
    target taken out after a ``submitted`` run; its rows stay as the reason). A
    ``submitted`` row gets no exemption: a mistyped slug would otherwise leave the real
    target in the table with the removal rule silently off. A row also needs a known OS,
    an opener that OS can take, a real ISO date, an ``https://`` evidence link with a
    host, and every free-text field filled in without a ``|`` or a line break (either
    would break the ADR's table). The date is not compared with today: this module reads
    no clock.
    """
    allowed = known_targets | removed_targets
    problems: list[str] = []
    for i, row in enumerate(rows):
        where = f"row {i} ({row.target})"
        if row.target not in allowed:
            problems.append(f"{where}: unknown target {row.target!r}")
        if row.os not in OPENERS_BY_OS:
            problems.append(f"{where}: unknown os {row.os!r}")
        elif row.opener not in OPENERS_BY_OS[row.os]:
            problems.append(
                f"{where}: opener {row.opener!r} is not one of {OPENERS_BY_OS[row.os]}"
            )
        if not _real_iso_date(row.date):
            problems.append(f"{where}: date {row.date!r} is not a real YYYY-MM-DD date")
        for name in ("environment", "client_version", "yazses_version", "tester", "evidence"):
            value = getattr(row, name)
            if not value.strip():
                problems.append(f"{where}: {name} is empty")
        if row.evidence.strip() and not _evidence_link(row.evidence):
            problems.append(f"{where}: evidence must be an https link to the record")
        cells = row.table_cells()
        if any("|" in cell for cell in cells):
            problems.append(f"{where}: a field holds '|', which breaks the ADR table")
        if any("\n" in cell or "\r" in cell for cell in cells):
            problems.append(f"{where}: a field holds a line break, which breaks the ADR table")
    return problems


def submitted_targets(rows: tuple[ValidationRow, ...]) -> frozenset[str]:
    """The targets any run saw submit the prompt on open (ADR-031 §5: remove them)."""
    return frozenset(r.target for r in rows if r.outcome is Outcome.SUBMITTED)


def verified_rows(slug: str, rows: tuple[ValidationRow, ...]) -> tuple[ValidationRow, ...]:
    """The rows that verify *slug*: pre-filled and not submitted, nothing else."""
    return tuple(
        r for r in rows if r.target == slug and r.outcome is Outcome.PREFILLED_NOT_SUBMITTED
    )


def verification_sentence(rows: tuple[ValidationRow, ...]) -> str:
    """What ``features info sendto`` says about the record (ADR-031 §5).

    With no verifying row: "Not yet verified against any real Claude or Codex app."
    Otherwise each verified client version with its OS and date, then the targets still
    unverified.
    """
    seen: list[str] = []
    missing: list[str] = []
    for slug, target in TARGETS.items():
        mine = verified_rows(slug, rows)
        if not mine:
            missing.append(target.label)
            continue
        seen.extend(
            f"{r.client_version} ({_OS_LABEL.get(r.os, r.os)}, {r.date})" for r in mine
        )
    if not seen:
        return "Not yet verified against any real Claude or Codex app."
    sentence = "Verified pre-filled and not sent on " + ", ".join(seen) + "."
    if missing:
        sentence += " Not yet verified: " + ", ".join(missing) + "."
    return sentence
