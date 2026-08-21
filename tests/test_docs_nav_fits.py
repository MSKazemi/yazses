"""The top-level nav must stay narrow enough to actually fit on screen.

`navigation.tabs` renders the top level of `nav:` as one horizontal bar that does
**not** scroll for the reader — Material only scrolls it programmatically, to the
active tab. When the entries stop fitting, the ones at the right-hand end are
simply clipped off with no affordance saying anything is there. `Roadmap` and
`Releases` sat in that dead zone: reachable by search, and by nothing else.

This is not a hypothetical regression. The list reached fourteen entries, and grew
to **fifteen** while the fix for it was being written — a new top-level tab is a
one-line diff that looks harmless in review and silently pushes the far end of the
bar off screen.

A true width check needs a browser; this guards the input that drives it. The
count is the thing a human controls in `mkdocs.yml`, and holding it down is what
keeps the bar inside its container. If a ninth entry is genuinely warranted,
measure the rendered width first:

    const n = document.querySelector('.md-tabs__list');
    n.scrollWidth - n.getBoundingClientRect().width;   // > 0 means clipped

and raise `MAX_TABS` deliberately, in the same commit, with the measurement in the
message. Nesting under an existing tab costs nothing and changes no URL —
`use_directory_urls: false` means regrouping `nav:` never moves a page.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MKDOCS = ROOT / "mkdocs.yml"

#: Eight fits with room to spare at every width where the bar is shown. See the
#: module docstring before changing this.
MAX_TABS = 8


def _nav_lines() -> list[str]:
    text = MKDOCS.read_text(encoding="utf-8")
    lines = text.split("\n")
    start = next(i for i, line in enumerate(lines) if line.startswith("nav:"))
    return lines[start + 1 :]


def top_level_tabs() -> list[str]:
    """The `nav:` entries Material renders as tabs -- indent exactly two spaces."""
    return [
        match.group(1).strip().strip('"')
        for line in _nav_lines()
        if (match := re.match(r"^  - ([^:]+):", line))
    ]


def test_the_tab_bar_cannot_silently_outgrow_its_container():
    tabs = top_level_tabs()
    assert tabs, "parsed no top-level nav entries -- this guard is checking nothing"
    assert len(tabs) <= MAX_TABS, (
        f"{len(tabs)} top-level nav tabs ({', '.join(tabs)}), but the bar fits "
        f"{MAX_TABS}. Material does not scroll it for the reader, so the entries "
        f"past the edge are unreachable. Nest the new one under an existing tab, "
        f"or measure the rendered width and raise MAX_TABS deliberately."
    )


def test_regrouping_the_nav_never_drops_a_page():
    """Reordering tabs is safe; silently losing a page while doing it is not.

    Deliberately *not* a "does this file exist?" check. The Engineering tier is
    copied into the docs tree by a build hook, so `design/*.md` entries resolve
    only during the build — a static existence test reports seven false failures,
    and `mkdocs build --strict` already validates nav targets properly, hooks
    included. What a static test *can* do, and strict cannot, is notice that a
    regroup changed the set of pages the nav offers.
    """
    pages = [
        match.group(1)
        for line in _nav_lines()
        if (match := re.search(r":\s*([A-Za-z0-9_./-]+\.md)\s*$", line))
    ]
    assert len(pages) == len(set(pages)), (
        f"the nav lists a page twice: "
        f"{sorted({p for p in pages if pages.count(p) > 1})}"
    )
    assert len(pages) > 100, (
        f"the nav offers only {len(pages)} pages -- a regroup that drops whole "
        f"sections looks exactly like this"
    )
