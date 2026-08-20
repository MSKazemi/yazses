"""`docs/install-cost.md` publishes a size for every optional feature. So does
`yazses features`. Nothing compared them, and on 2026-08-20 six of the eleven published
rows were wrong -- `stt-parakeet` was listed at **~4 MB**, beside `chinese-script`, when
it fetches a ~600 MB model and is the second-largest thing YazSes can pull down.

That page's whole premise is its first paragraph: *"These are measured numbers, not
estimates, so you can decide before you start."* A stale figure there is not a cosmetic
docs problem, it is the page contradicting the promise it opens with -- and it is the
same defect shape as the one that produced the wrong figure in the first place: two
committed facts one file apart, with nothing holding them equal.

The Packages column is deliberately **not** checked. It counts a resolved distribution
closure measured out-of-band by `scripts/gen-feature-sizes.py`, not something this test
can recompute, and asserting a number it cannot derive would be theatre.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from yazses.system import depsize

REPO = pathlib.Path(__file__).resolve().parents[1]
PAGE = REPO / "docs" / "install-cost.md"

#: Rows below this are prose, not the feature table.
_ROW = re.compile(r"^\|\s*(`[^|]+?)\s*\|\s*\*{0,2}(~[^|*]+?)\*{0,2}\s*\|\s*\d+\s*\|$", re.M)


def _published() -> list[tuple[tuple[str, ...], str]]:
    """Every `| slugs | size | packages |` row, as (slugs, size-label)."""
    rows = []
    for names, size in _ROW.findall(PAGE.read_text(encoding="utf-8")):
        slugs = tuple(re.findall(r"`([^`]+)`", names))
        rows.append((slugs, size.strip()))
    return rows


def test_the_table_is_actually_being_read():
    """A regex that matches nothing passes every assertion below it."""
    rows = _published()
    assert len(rows) >= 10, f"only parsed {len(rows)} rows -- the table's shape changed"
    flat = [s for slugs, _ in rows for s in slugs]
    assert "stt-parakeet" in flat, flat


@pytest.mark.parametrize("slugs,size", _published())
def test_every_published_size_is_the_one_the_tool_reports(slugs, size):
    for slug in slugs:
        expected = depsize.catalogue_size_label(slug, has_pip_deps=True)
        assert expected, f"{slug} is published at {size} but the tool reports no size"
        assert size == expected, (
            f"docs/install-cost.md publishes {slug} at {size}, `yazses features` says "
            f"{expected}. Regenerate the row -- the page promises measured numbers."
        )


def test_every_feature_that_fetches_a_model_is_on_the_page():
    """The row that was wrong was wrong because nobody looked at it for a year.

    A feature that pulls model files down is exactly the one a reader consults this page
    about, so it may not be absent from it.
    """
    published = {s for slugs, _ in _published() for s in slugs}
    for slug in sorted(depsize._MODEL_MB):
        if depsize.fetches_a_model(slug):
            assert slug in published, (
                f"{slug} downloads model files but install-cost.md never mentions it"
            )


def _legend() -> str:
    """The prose between the feature table and the next heading.

    Scoped deliberately. Searching the whole page for "floor" passes on three unrelated
    sentences elsewhere that use the word about the base install -- the identical
    mistake this suite exists to catch, made inside the suite itself.
    """
    text = PAGE.read_text(encoding="utf-8")
    rows = [m for m in _ROW.finditer(text)]
    assert rows, "no table rows -- cannot locate the legend"
    after = text[rows[-1].end():]
    return after.split("\n#", 1)[0]


def test_the_plus_suffix_is_explained_where_it_appears():
    """An unexplained `+` on a number reads as a typo, not as 'this is a floor'."""
    if not any(size.endswith("+") for _, size in _published()):
        pytest.skip("no floor-valued row is currently published")
    legend = _legend()
    assert "`+`" in legend and "floor" in legend, (
        "a row is published with a trailing `+` and the text under the table never says "
        f"what it means; found: {legend.strip()[:200]!r}"
    )
