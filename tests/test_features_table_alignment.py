"""`yazses features` is the discovery surface for 147 capabilities, so it has to scan.

The columns were fixed minimum widths (`:<32`, `:<16`). Any longer value pushed
DOWNLOAD and ADVICE right *for that row alone*, so the table quietly went ragged as
names and slugs grew: 10 of 147 rows by 2026-08-16, and adding one 22-character
slug (`overlay-reduced-motion`) made it 11. Nothing failed, because nothing looked.

The two columns are deliberately not treated the same, and that is the property most
worth pinning:

* **TOGGLE NAME is copied** into `yazses features enable <name>`. It grows to fit and
  is never truncated — a clipped slug is a command that does not run.
* **NAME is prose** and may be clipped; `yazses features info` carries the full text.
"""

from __future__ import annotations

import re

from typer.testing import CliRunner

from yazses.cli import app
from yazses.system.features import _registry

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_ROW = re.compile(r"│  [●○]")
_TIERS = ("core", "recommended", "optional", "experimental", "planned")


def _rows() -> list[str]:
    result = CliRunner().invoke(app, ["features"])
    assert result.exit_code == 0, result.output
    lines = [_ANSI.sub("", ln) for ln in result.output.splitlines()]
    rows = [ln for ln in lines if _ROW.match(ln)]
    assert rows, "no capability rows rendered — this guard would pass on an empty table"
    return rows


def test_every_row_starts_its_advice_column_at_the_same_offset():
    """One ragged row is a formatting bug; the point is that none may be."""
    starts = set()
    for row in _rows():
        match = re.search(rf"\b({'|'.join(_TIERS)})\b", row[40:])
        assert match, f"no advice tier found in row: {row!r}"
        starts.add(40 + match.start())
    assert len(starts) == 1, (
        f"the ADVICE column lands at {sorted(starts)} across rows — a long NAME or "
        "TOGGLE NAME is pushing later columns right on some rows only"
    )


def test_no_toggle_name_is_truncated():
    """The column people copy from must survive intact, whatever its length.

    This is the half that a naive "just clip everything to the column width" fix
    would break, and it would break it silently: the table would look perfect and
    `yazses features enable overlay-reduced-moti…` would not run.
    """
    rendered = "\n".join(_rows())
    for definition in _registry():
        assert definition.slug in rendered, (
            f"{definition.slug!r} does not appear intact in the table — a truncated "
            "toggle name is a command that does not run"
        )


def test_the_longest_slug_is_actually_exercised():
    """Guards the guard: the checks above are vacuous if nothing is long.

    The column was 16 wide, so a registry whose longest slug fits in 16 would pass
    them while the overflow bug sat untouched.
    """
    longest = max(len(d.slug) for d in _registry())
    assert longest > 16, (
        f"longest slug is {longest} chars, within the old fixed width — this suite "
        "no longer exercises the overflow it exists to catch"
    )
