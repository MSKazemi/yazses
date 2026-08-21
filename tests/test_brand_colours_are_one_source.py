"""The brand colour is declared once and re-typed in five other files.

`branding.py` holds `BRAND_TOP` and `BRAND_BOTTOM`. Those same two values are typed
again as literal hex in the packaged SVG, the favicon, the social preview, the docs
stylesheet and `mkdocs.yml` — none of which imports anything.

`tests/test_brandmark.py` already guards the *geometry* against the source SVG
(`test_geometry_matches_the_source_svg`), which is the same class of drift and the
reason that guard exists. Nothing guarded the colour. So changing the brand would
repaint the application and quietly leave the website, the favicon, the social card
and the packaged icon on the old one — a split visible to everyone except whoever
made the change.

Asserted per surface rather than as a repo-wide grep: each of these is a
deliberate copy with a known reason (an SVG cannot import Python, mkdocs.yml is
read by mkdocs), so the fix is not to remove them but to notice when they diverge.
Case-insensitive, because the packaged SVG writes `#7C4DFF` and the CSS writes
`#7c4dff`, and both are correct.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from yazses.branding import BRAND_BOTTOM, BRAND_TOP

ROOT = Path(__file__).resolve().parent.parent


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % rgb


#: file -> the brand colours it must carry. Some surfaces use only the darker end
#: (a flat background), which is a design choice rather than drift.
SURFACES: dict[str, tuple[str, ...]] = {
    "contrib/icons/yazses.svg": ("top", "bottom"),
    "docs/assets/favicon.svg": ("top", "bottom"),
    "docs/assets/extra.css": ("top", "bottom"),
    "docs/assets/social-preview.svg": ("bottom",),
    "mkdocs.yml": ("bottom",),
}


def test_the_constants_are_still_there() -> None:
    """Guard the guard: a rename would make every assertion below vacuous."""
    assert len(BRAND_TOP) == 3 and len(BRAND_BOTTOM) == 3
    assert BRAND_TOP != BRAND_BOTTOM, "a gradient needs two ends"


@pytest.mark.parametrize("relpath,ends", sorted(SURFACES.items()))
def test_every_brand_surface_carries_the_declared_colour(relpath: str, ends: tuple[str, ...]) -> None:
    path = ROOT / relpath
    if not path.is_file():
        pytest.fail(f"{relpath} is gone — remove it from SURFACES or restore it")

    text = path.read_text(encoding="utf-8").lower()
    wanted = {"top": _hex(BRAND_TOP), "bottom": _hex(BRAND_BOTTOM)}
    for end in ends:
        assert wanted[end] in text, (
            f"{relpath} does not carry {wanted[end]} ({end} of the brand gradient, "
            f"from branding.py). If the brand colour changed, this file needs the "
            f"same edit — it cannot import the constant."
        )


def test_no_surface_still_carries_a_colour_the_brand_has_moved_off() -> None:
    """The other direction: a half-done change leaves the old value behind.

    Catches the specific mess where someone updates branding.py and three of the
    five files, and the remaining two keep painting the previous brand.
    """
    current = {_hex(BRAND_TOP), _hex(BRAND_BOTTOM)}
    # The two values this project has actually shipped. A stale one appearing in a
    # brand surface means a partial change.
    historical = {"#7c4dff", "#4527a0"}
    stale = historical - current
    if not stale:
        pytest.skip("the brand has not changed, so there is no stale value to find")

    for relpath in SURFACES:
        text = (ROOT / relpath).read_text(encoding="utf-8").lower()
        found = [old for old in stale if old in text]
        assert not found, f"{relpath} still carries the previous brand colour {found}"
