"""Every %changelog weekday must match its date.

`rpmbuild` warns "bogus date in %changelog" when the weekday and the date disagree, and
rpmlint reports it as an error. It is a warning rather than a build failure, which is
exactly why it survives: the package still builds, so nothing stops and nobody looks.

Both entries in packaging/fedora/yazses.spec were wrong when this was written -- the
2026-08-14 line had shipped that way since the spec was authored, and the 2.36.0 line I
added inherited the same mistake by being written the same way, from memory rather than
from a calendar. A human writing a date by hand gets the weekday wrong; a test does not.

Stdlib only (re, datetime) so it runs on every leg including FreeBSD, where neither rpm
tooling nor Pillow exists.
"""

from __future__ import annotations

import datetime
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _is_rpm_spec(path: Path) -> bool:
    """True for an RPM spec, false for a PyInstaller one.

    Both use the .spec extension and they share a directory tree, so the extension alone
    selects the wrong files -- packaging/windows/yazses.spec and packaging/macos/yazses.spec
    are Python. Detecting by content keeps this derived rather than a hand-written list
    that a future .spec would silently fall outside of.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return "%changelog" in text and re.search(r"^Name:", text, re.M) is not None


SPECS = sorted(p for p in ROOT.glob("packaging/**/*.spec") if _is_rpm_spec(p))

# "* Fri Aug 14 2026 Name <email> - 2.18.2-1"
ENTRY = re.compile(
    r"^\*\s+(?P<dow>[A-Z][a-z]{2})\s+(?P<mon>[A-Z][a-z]{2})\s+(?P<day>\d{1,2})\s+(?P<year>\d{4})\s"
)


def _entries(spec: Path) -> list[tuple[int, str, datetime.date]]:
    out = []
    for lineno, line in enumerate(spec.read_text(encoding="utf-8").splitlines(), 1):
        m = ENTRY.match(line)
        if not m:
            continue
        date = datetime.datetime.strptime(
            f"{m['day']} {m['mon']} {m['year']}", "%d %b %Y"
        ).date()
        out.append((lineno, m["dow"], date))
    return out


def test_there_is_at_least_one_spec_to_check() -> None:
    """A guard that iterates is green on an empty collection; prove the set is not empty."""
    assert SPECS, "no .spec files found under packaging/ — this guard would pass vacuously"


@pytest.mark.parametrize("spec", SPECS, ids=lambda p: p.name)
def test_the_spec_has_changelog_entries(spec: Path) -> None:
    assert _entries(spec), f"{spec.relative_to(ROOT)} has no parseable %changelog entries"


@pytest.mark.parametrize("spec", SPECS, ids=lambda p: p.name)
def test_every_changelog_weekday_matches_its_date(spec: Path) -> None:
    wrong = [
        f"{spec.relative_to(ROOT)}:{lineno} says {dow} but {date.isoformat()} is a "
        f"{date.strftime('%a')}"
        for lineno, dow, date in _entries(spec)
        if dow != date.strftime("%a")
    ]
    assert not wrong, "rpmbuild reports these as 'bogus date in %changelog':\n  " + "\n  ".join(wrong)


@pytest.mark.parametrize("spec", SPECS, ids=lambda p: p.name)
def test_changelog_entries_are_newest_first(spec: Path) -> None:
    """rpm expects descending order; an out-of-order entry is a second rpmlint complaint."""
    dates = [date for _, _, date in _entries(spec)]
    assert dates == sorted(dates, reverse=True), (
        f"{spec.relative_to(ROOT)} %changelog is not newest-first: "
        f"{[d.isoformat() for d in dates]}"
    )
