"""A page that mentions the Tier-2 SLM router must say it is not wired.

`commands/slm_router.py` is in `test_orphan_modules.py::KNOWN_ORPHANS`:
*"grammar.py takes an `slm_router` parameter and nothing ever constructs one — a
plumbed seam never filled."* Only a `_SlmRouter` **Protocol** exists; no code builds
a router, and Tier 1 decides every utterance.

The README says so twice — *"designed but **not wired yet**"*. The documentation
mostly did not. Seven pages presented it as an available option:

* `docs/index.md` — the front door, three times, including the pipeline diagram
* `docs/faq.md` — twice, on the page written for search and answer engines
* `docs/comparison.md` — **in the competitive table**, as a YazSes capability
* `docs/benchmarks.md` — *"the optional Tier-2 SLM router exists to catch those"*,
  next to a measured command-recognition number it does not contribute to
* `docs/diagrams/` — the Mermaid architecture box and its `.mmd` source
* `docs/hi/index.md`, `docs/ru/index.md` — inherited from the old English index

`docs/architecture.md` and `docs/use-cases/voice-commands.md` were already honest, and
they show the two shapes that work: prose that says *"is **not wired**"*, and a
`!!! warning "Tier 2 is designed, not wired"` immediately after the claim.

## Why page-level, and why tied to the ledger

Page-level rather than proximity: the two honest pages put the caveat in different
places relative to the claim, and a distance rule would fail one of them for being
correct in the wrong shape.

Tied to `KNOWN_ORPHANS`, so this stops demanding a caveat the day the router is
actually wired — a guard that outlives its premise starts forcing a lie.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

DOCS = Path(__file__).resolve().parents[1] / "docs"
#: Release notes describe what a past version claimed; rewriting them would be a
#: different kind of untruth.
SKIP_TREES = {"releases"}

_MENTION = re.compile(r"slm[ _-]?router|tier[ -]?2 slm", re.IGNORECASE)
_QUALIFIER = re.compile(r"not wired|not yet wired|designed, not", re.IGNORECASE)


def _pages() -> list[Path]:
    return [
        p
        for p in sorted(list(DOCS.rglob("*.md")) + list(DOCS.rglob("*.mmd")))
        if not (SKIP_TREES & set(p.parts))
    ]


def test_the_router_is_still_unwired() -> None:
    """The premise. When this fails, delete the caveats rather than the guard."""
    from test_orphan_modules import KNOWN_ORPHANS

    assert "commands.slm_router" in KNOWN_ORPHANS, (
        "commands.slm_router left the orphan ledger — if Tier 2 is wired now, remove "
        "the 'not wired' caveats from the docs and delete this test in the same commit"
    )


def test_the_scan_finds_the_mentions() -> None:
    """A guard over an empty set passes on everything."""
    pages = _pages()
    assert len(pages) > 50, f"only {len(pages)} doc pages found"
    mentioning = [p for p in pages if _MENTION.search(p.read_text(encoding="utf-8"))]
    assert len(mentioning) >= 3, f"only {len(mentioning)} pages mention the router"


#: How far a caveat may sit from the mention it qualifies. Measured, not guessed:
#: `architecture.md` puts it on the same line (gap 0) and `voice-commands.md` uses an
#: admonition eleven lines below the bullet. A page-level rule was tried first and is
#: too weak — `comparison.md` carried "not yet wired" about a *different* feature far
#: down the page, which silently excused a bare claim in its competitive table.
_CAVEAT_WINDOW = 15


def test_every_mention_has_a_caveat_near_it() -> None:
    bad: list[str] = []
    for path in _pages():
        lines = path.read_text(encoding="utf-8").splitlines()
        caveats = [i for i, line in enumerate(lines) if _QUALIFIER.search(line)]
        for i, line in enumerate(lines):
            if not _MENTION.search(line):
                continue
            if not any(abs(i - c) <= _CAVEAT_WINDOW for c in caveats):
                bad.append(f"{path.relative_to(DOCS.parent)}:{i + 1}: {line.strip()[:70]}")
    bad = sorted(bad)
    assert not bad, (
        "these pages present the Tier-2 SLM router as available; nothing constructs "
        "one and Tier 1 decides every utterance:\n  " + "\n  ".join(bad)
        + "\n\nSay 'designed, not wired' as architecture.md and voice-commands.md do, "
        "or drop the mention."
    )


@pytest.mark.parametrize(
    "text,flagged",
    [
        ("a regex grammar plus an optional SLM router", True),
        ("Tier 2 SLM router, designed, not wired", False),
        ("the slm_router.py module is **not wired**", False),
        ("a regex grammar maps phrases to keys", False),
    ],
)
def test_the_check_catches_the_shape_and_allows_the_fix(text: str, flagged: bool) -> None:
    """Only worth having if it fires — and only keepable if it does not cry wolf."""
    assert bool(_MENTION.search(text) and not _QUALIFIER.search(text)) is flagged
