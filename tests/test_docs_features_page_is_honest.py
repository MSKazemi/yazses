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

The first fix marked those rows ◌ and left them in the wave tables, between the
features that work. That still advertised them (issue #646, ADR-030 Pillar 1.4), and the
mark drifted: "Multi-User Profiles" sat unmarked for months because its toggle cell
named the config key (`voiceprint` `multi_profile`) instead of the slug `multiprofile`.

So the page now has one shape, and it is mechanical: the wave tables hold **only**
wired capabilities, every unwired one appears exactly once under **Designed, not
built** with a link to its design record, and the two sets are compared against the
registry -- by toggle *and* by display name, so a row cannot hide behind a key name.
Wiring a feature moves its row, or the build goes red. Every extra the docs name must
also exist in `pyproject.toml`.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

from yazses.config import Config
from yazses.system.features import feature_status, unwired_slugs

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs" / "v2-features.md"
#: The retired in-table mark. Its return would mean an unwired row is back in a table.
MARK = "◌"
DESIGNED_HEADING = "## Designed, not built"
_ADR_LINK = re.compile(
    r"\(https://github\.com/MSKazemi/yazses/blob/main/(design/adr/adr-[a-z0-9-]+\.md)\)"
)


def _declared_extras() -> set[str]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return set(data["project"].get("optional-dependencies", {}))


def _rows() -> list[tuple[int, str, str, list[str], bool]]:
    """(line, feature cell, bold name, toggles, in the designed section) per row.

    A feature row is a table row whose first cell starts with a bold name. Rows of the
    "four that answer to the machine" table start with a backticked toggle instead and
    are not feature rows.
    """
    rows = []
    designed = False
    for lineno, line in enumerate(PAGE.read_text(encoding="utf-8").splitlines(), 1):
        if line.startswith("## "):
            designed = line.strip() == DESIGNED_HEADING
            continue
        if not line.startswith("|") or "**" not in line:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or not cells[0].lstrip(MARK).strip().startswith("**"):
            continue
        name = re.search(r"\*\*(.+?)\*\*", cells[0])
        rows.append((
            lineno, cells[0], name.group(1) if name else "",
            re.findall(r"`([^`]+)`", cells[1]), designed,
        ))
    return rows


def _wave_rows():
    return [r for r in _rows() if not r[4]]


def _designed_rows():
    return [r for r in _rows() if r[4]]


def _unwired_names() -> dict[str, str]:
    """Registry display name -> slug, for every unwired capability."""
    unwired = unwired_slugs()
    return {f.name: f.slug for f in feature_status(Config()) if f.slug in unwired}


def test_the_page_actually_parses_into_rows():
    """Every guard below iterates; on an empty parse they would all pass."""
    assert len(_wave_rows()) > 80, len(_wave_rows())
    assert _designed_rows(), f"no rows under {DESIGNED_HEADING!r} -- heading renamed?"
    assert PAGE.read_text(encoding="utf-8").count(DESIGNED_HEADING) == 1


@pytest.mark.parametrize("lineno,cell,name,toggles,_designed", _wave_rows())
def test_no_unwired_capability_sits_in_a_wave_table(lineno, cell, name, toggles, _designed):
    """The issue itself: a feature table lists only what `features enable` turns on.

    Checked by toggle and by registry display name. The name catches the row that
    shipped unmarked: "Multi-User Profiles" named the config key, not the slug.
    """
    unwired = unwired_slugs()
    by_toggle = [t for t in toggles if t in unwired]
    by_name = _unwired_names().get(name)
    if by_toggle or by_name:
        pytest.fail(
            f"v2-features.md:{lineno} {cell} is a wave-table row for "
            f"{by_toggle or [by_name]}, which `features enable` refuses -- move it to "
            f"{DESIGNED_HEADING!r}"
        )


def test_the_designed_section_is_exactly_the_unwired_set():
    """Both directions: nothing unwired is missing, nothing wired is listed as unbuilt."""
    listed: list[str] = []
    for lineno, _cell, _name, toggles, _d in _designed_rows():
        assert len(toggles) == 1, f"v2-features.md:{lineno} must name exactly one slug"
        listed.append(toggles[0])
    assert len(listed) == len(set(listed)), f"a capability is listed twice: {listed}"
    unwired = set(unwired_slugs())
    missing = sorted(unwired - set(listed))
    wired = sorted(set(listed) - unwired)
    assert not missing, f"unwired capabilities missing from {DESIGNED_HEADING!r}: {missing}"
    assert not wired, (
        f"listed under {DESIGNED_HEADING!r} but wired now -- move them back into their "
        f"wave's table: {wired}"
    )


def test_every_designed_row_links_a_design_record_that_exists():
    """"Keep each row's ADR link": the section is where a contributor starts."""
    for lineno, cell, _name, _toggles, _d in _designed_rows():
        line = PAGE.read_text(encoding="utf-8").splitlines()[lineno - 1]
        link = _ADR_LINK.search(line)
        assert link, f"v2-features.md:{lineno} {cell} has no design/adr/ link"
        assert (ROOT / link.group(1)).is_file(), (
            f"v2-features.md:{lineno} links {link.group(1)}, which does not exist"
        )


def test_the_retired_mark_is_gone():
    """◌ meant "unwired, but listed among the features". That shape is what #646 removed."""
    assert MARK not in PAGE.read_text(encoding="utf-8")


def test_the_page_explains_the_section_and_counts_it_from_the_registry():
    """The legend names the section and states the count inside a generated marker."""
    text = PAGE.read_text(encoding="utf-8")
    assert "(#designed-not-built)" in text
    assert "yazses features enable" in text
    counts = re.findall(r"<!-- registry:unwired -->([0-9]+)<!-- /registry -->", text)
    assert counts, "the page no longer states the unwired count from the registry"
    assert {int(c) for c in counts} == {len(unwired_slugs())} == {len(_designed_rows())}


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
