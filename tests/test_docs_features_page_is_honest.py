"""The v2 features page must not promise what this build cannot do.

`docs/v2-features.md` is the public catalogue of the v2 interaction layer, and its
own instructions are *"Manage all of them with `yazses features enable <name>`"*.
That command **refuses** any capability in `_UNWIRED`:

    $ yazses features enable snippets
    Voice Snippets is designed but not yet wired into this build — enabling it
    would change nothing (no runtime code reads its config yet).

Half the page was in that state -- 61 of 122 rows -- with nothing on the page saying
so, and six rows went further and named a pip extra that does not exist
(`affect`, `predict`, `scribe`, `rag`, `codec`, `voiceguard`), so the documented
install route failed too. A seventh named DeepFilterNet as the content of the
`denoise` extra, which ships `noisereduce` instead -- DeepFilterNet caps
`numpy<2.0` against this project's `numpy>=2.4.6` and can never be installed here.

Both halves are now mechanical: a row whose toggle is unwired must carry ◌, a wired
row must not, and every extra the docs name must exist in `pyproject.toml`. Wiring a
feature and un-marking its row therefore happen together, or the build goes red.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

from yazses.system.features import unwired_slugs

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs" / "v2-features.md"
MARK = "◌"


def _declared_extras() -> set[str]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return set(data["project"].get("optional-dependencies", {}))


def _rows() -> list[tuple[int, str, list[str], bool]]:
    """(line, feature cell, toggle slugs, is marked) for each feature row."""
    rows = []
    for lineno, line in enumerate(PAGE.read_text(encoding="utf-8").splitlines(), 1):
        if not line.startswith("|") or "**" not in line:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or not cells[0].lstrip(MARK).strip().startswith("**"):
            continue
        rows.append((lineno, cells[0], re.findall(r"`([^`]+)`", cells[1]), cells[0].startswith(MARK)))
    return rows


def test_the_page_actually_parses_into_rows():
    """Every guard below iterates; on an empty parse they would all pass."""
    rows = _rows()
    assert len(rows) > 100, len(rows)
    assert any(marked for *_, marked in rows)
    assert any(not marked for *_, marked in rows)


@pytest.mark.parametrize("lineno,cell,toggles,marked", _rows())
def test_an_unwired_row_says_so(lineno, cell, toggles, marked):
    unwired = unwired_slugs()
    should = any(t in unwired for t in toggles)
    if should and not marked:
        pytest.fail(
            f"v2-features.md:{lineno} {cell.strip()} lists {toggles}, which "
            f"`features enable` refuses — prefix the row with {MARK}"
        )
    if marked and not should:
        pytest.fail(
            f"v2-features.md:{lineno} {cell.strip()} is marked {MARK} but {toggles} "
            "is wired — drop the mark now that it works"
        )


def test_the_legend_counts_match_the_table():
    """The page states the numbers out loud; drift must fail rather than mislead."""
    rows = _rows()
    marked = sum(1 for *_, m in rows if m)
    text = PAGE.read_text(encoding="utf-8")
    claim = re.search(r"\*\*(\d+) of the (\d+) rows below are ◌ today\.\*\*", text)
    assert claim, "the legend no longer states the counts; re-point this guard"
    assert (int(claim.group(1)), int(claim.group(2))) == (marked, len(rows))


def test_the_legend_explains_the_mark():
    text = PAGE.read_text(encoding="utf-8")
    assert "planned: designed, not built yet" in text
    assert "yazses features enable" in text


# ---- extras the docs send people to must exist --------------------------

_EXTRA = re.compile(r"(?:the `([a-z0-9_.-]+)` extra)|(?:yazses\[([a-z0-9_,.-]+)\])")


def _doc_pages() -> list[Path]:
    """Top-level user pages only.

    `docs/releases/` is excluded on purpose: a release note is a dated record of
    what was said at the time, and rewriting one to match today's packaging would
    make it a worse record, not a better one.
    """
    return sorted(p for p in (ROOT / "docs").glob("*.md"))


def test_there_are_doc_pages_to_check():
    assert len(_doc_pages()) > 20


@pytest.mark.parametrize("page", _doc_pages(), ids=lambda p: p.name)
def test_every_extra_the_docs_name_exists(page):
    declared = _declared_extras()
    bad = []
    for lineno, line in enumerate(page.read_text(encoding="utf-8").splitlines(), 1):
        for match in _EXTRA.finditer(line):
            for group in match.groups():
                if not group:
                    continue
                for name in group.split(","):
                    name = name.strip()
                    if name and name not in declared:
                        bad.append(f"{page.name}:{lineno} names extra {name!r}")
    assert not bad, (
        "the docs send a reader to a pip extra that does not exist in "
        f"pyproject.toml (declared: {sorted(declared)}):\n  " + "\n  ".join(bad)
    )


def test_the_denoise_row_names_what_the_extra_actually_installs():
    """DeepFilterNet caps numpy<2.0 against this project's numpy>=2.4.6, so the
    `denoise` extra ships `noisereduce`. Naming the wrong one sends a reader after
    an install that cannot resolve on any Python version."""
    text = PAGE.read_text(encoding="utf-8")
    row = next(ln for ln in text.splitlines() if "**Noise Suppression**" in ln)
    assert "noisereduce" in row
    assert "not* installable" in row or "not installable" in row
