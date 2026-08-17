"""Docs must not tell you to enable a feature that `features enable` refuses.

`system/features.py` says it plainly: a capability with `wired = False` is "designed
but not yet wired into any runtime path: enabling it would write a config key nothing
reads. `features enable` refuses these." `yazses features` labels them **planned —
designed, not yet wired**, and `#164` invites contributors to wire one.

The documentation did not carry that distinction. Eight pages listed unwired
capabilities in ordinary "Capability | Enable with | For" tables, alongside features
that work, with the enable command spelled out and nothing to say it would be refused.
The accessibility page was the worst of them: six unwired slugs offered to the readers
least able to route around a dead end.

The rule this pins is deliberately narrow: **a line that spells out `yazses features
enable <slug>` for an unwired slug must also say `planned`.** Mentioning the capability
is fine and good — that is how a contributor finds something to wire. Handing someone a
command that cannot work is not.

It follows `_UNWIRED` rather than a copied list, so wiring a feature and removing it
from that set retires the marker requirement automatically, and adding a new unwired
capability puts the requirement in place the day it lands.
"""
from __future__ import annotations

import re
from pathlib import Path

from yazses.system.features import _UNWIRED

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

#: Release notes describe what a version did at the time and must not be rewritten.
SKIP_DIRS = {"releases"}


def _pages() -> list[Path]:
    return [
        p
        for p in DOCS.rglob("*.md")
        if not SKIP_DIRS & set(part for part in p.relative_to(DOCS).parts)
    ]


#: How far above the command the caveat may sit. A fenced code block cannot carry an
#: inline marker without rendering it literally, so the sentence introducing the block
#: counts. Six lines is the paragraph directly above plus the blank line and the fence
#: — close enough that a reader cannot miss it, tight enough that an unrelated mention
#: elsewhere on the page does not satisfy it.
CONTEXT_LINES = 6


def _offenders() -> list[str]:
    out: list[str] = []
    for page in _pages():
        lines = page.read_text(encoding="utf-8").splitlines()
        for n, line in enumerate(lines, 1):
            for slug in _UNWIRED:
                if not re.search(rf"features enable {re.escape(slug)}\b", line):
                    continue
                window = lines[max(0, n - 1 - CONTEXT_LINES):n]
                if not any("planned" in w.lower() for w in window):
                    rel = page.relative_to(ROOT)
                    out.append(f"{rel}:{n} — `features enable {slug}` (unwired)")
    return sorted(out)


def test_no_page_hands_out_an_enable_command_that_will_be_refused():
    bad = _offenders()
    assert not bad, (
        "these lines tell a reader to enable a capability that `features enable` "
        "refuses; mark them 'planned' (or wire the feature and remove it from "
        "_UNWIRED):\n  " + "\n  ".join(bad)
    )


def test_the_check_is_looking_at_something():
    """Guards the guard: an empty `_UNWIRED` or a broken glob would pass silently."""
    assert _UNWIRED, "no unwired features — has the registry moved?"
    assert len(_pages()) > 20, f"only {len(_pages())} docs pages found; glob is wrong"
