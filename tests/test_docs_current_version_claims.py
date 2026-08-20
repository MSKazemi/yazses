"""Every "this is the current release" claim must agree with `pyproject.toml`.

This is the one class of documentation drift the project keeps repeating. The
counts beside these claims already have a guard — `ROADMAP.md` carries the two
commands that re-derive them and tells you not to edit them by hand — but the
*version* in the same sentence was checked by nothing. So it rotted, silently and
repeatedly:

- `docs/releases/index.md` announced 2.17.0 as "Current stable" three releases
  after 2.20.0 shipped, and the five intervening versions had no note page at all.
- `docs/index.md` carried `"softwareVersion": "2.17.0"` inside the schema.org
  block. That one is worse than a stale sentence, because it is the
  machine-readable answer: it is what search engines and answer engines quote.
- `README.md` — the repository's front door — said `v2.17.0, installed &
  maintained`, and the line had been copied into the Hindi and Russian
  translations, so one stale fact appeared in three places.
- `ROADMAP.md` said `Stable release: v2.18.2` and `On main (v2.18.2 ...)`.

Every one of those was found by reading pages by hand, which is exactly the
process that had already missed them for three releases. Hence this file.

**What this does not do.** It deliberately does not check historical statements.
`docs/roadmap.md`'s shipped table, the per-version release notes and the changelog
all name old versions correctly and must keep doing so. Only the phrasings that
assert *currency* are matched, each anchored to its file so a new stale claim
somewhere else is a new test, not a silent pass.
"""

from __future__ import annotations

import ast
import inspect
import json
import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

def _is_full_run(config) -> bool:
    """Whether this invocation collected the whole suite, asked of pytest directly.

    This used to be "did we collect at least 1000 tests", which answers a different
    question and gets the answer wrong in both directions as the suite grows. At 7000+
    tests an ordinary `-k "docs"` clears 1000 and then fails the floor -- a red that
    means nothing, in a test whose own docstring says a guard that cries wolf during
    development gets deleted.

    Every option below *removes* tests from the run. Naming a file or a node id is a
    subset; naming a directory (or nothing, so `testpaths` applies) is not. Nothing here
    is derived from the claimed floor, which was the earlier version's point and still
    holds: scaling the threshold off the floor would make an absurd floor *skip* the
    check instead of failing it.
    """
    opt = config.option
    if getattr(opt, "keyword", "") or getattr(opt, "markexpr", ""):
        return False
    if getattr(opt, "deselect", None) or getattr(opt, "ignore", None):
        return False
    if getattr(opt, "lf", False) or getattr(opt, "failedfirst", False):
        return False
    targets = list(getattr(opt, "file_or_dir", []) or [])
    # A node id (`file.py::test_x`) needs no stripping -- it is not a directory with
    # the suffix on or off, so splitting it would be a distinction without a verdict.
    return all(Path(t).is_dir() for t in targets)


def current_version() -> str:
    """The version the project claims to be, from the one authoritative file."""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


# (path, regex with one capture group holding the version, human description).
# Each pattern is anchored to the phrasing that asserts currency, never to a bare
# version string -- `docs/roadmap.md` is full of correct historical versions.
CURRENCY_CLAIMS = [
    (
        "docs/releases/index.md",
        r"## Current stable\s*\n+\*\*\[YazSes ([0-9]+\.[0-9]+\.[0-9]+)\]",
        'the "Current stable" heading on the release index',
    ),
    (
        "docs/roadmap.md",
        r"\*\*The current stable release is v([0-9]+\.[0-9]+\.[0-9]+)\*\*",
        "the roadmap's opening sentence",
    ),
    (
        "ROADMAP.md",
        r"\*\*Stable release: v([0-9]+\.[0-9]+\.[0-9]+)\*\*",
        "the ROADMAP.md headline",
    ),
    (
        "ROADMAP.md",
        r"On `main` \(v([0-9]+\.[0-9]+\.[0-9]+) plus the unreleased frontier\)",
        "the ROADMAP.md 'on main' line",
    ),
]

# The "Active -- current product" comparison row, which was copied verbatim into
# the translations. Globbing rather than listing them is the point: a new
# translation inherits the guard the day it lands, which is the lesson from the
# Zenodo badge check that was hard-coded to two files and let two others through.
STATUS_ROW = re.compile(
    r"current product\*\* \(v([0-9]+\.[0-9]+\.[0-9]+), installed"
)


@pytest.mark.parametrize("relpath,pattern,description", CURRENCY_CLAIMS)
def test_currency_claim_matches_pyproject(relpath, pattern, description):
    text = (ROOT / relpath).read_text(encoding="utf-8")
    match = re.search(pattern, text)
    assert match is not None, (
        f"{description} ({relpath}) no longer matches the expected phrasing, so "
        f"nothing is checking it any more. Update the pattern in this test rather "
        f"than deleting the case."
    )
    assert match.group(1) == current_version(), (
        f"{description} says {match.group(1)}, but pyproject.toml says "
        f"{current_version()}."
    )


def test_status_row_matches_pyproject_in_every_language():
    """The row is copied into each translated README; all copies must agree."""
    files = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*/index.md"))]
    stale = {}
    checked = 0
    for path in files:
        match = STATUS_ROW.search(path.read_text(encoding="utf-8"))
        if match is None:
            continue
        checked += 1
        if match.group(1) != current_version():
            stale[str(path.relative_to(ROOT))] = match.group(1)
    assert checked, "the status row vanished -- this guard is now checking nothing"
    assert not stale, (
        f"pyproject.toml says {current_version()}, but the status row is stale in: "
        f"{stale}"
    )


def test_schema_org_software_version_matches_pyproject():
    """The JSON-LD version is what search and answer engines actually quote."""
    text = (ROOT / "docs" / "index.md").read_text(encoding="utf-8")
    versions = re.findall(r'"softwareVersion":\s*"([^"]+)"', text)
    assert versions, "no softwareVersion in the home page JSON-LD -- guard is blind"
    assert set(versions) == {current_version()}, (
        f"schema.org softwareVersion is {versions}, pyproject.toml says "
        f"{current_version()}"
    )


def test_every_released_version_has_a_release_note_page():
    """A shipped version with no page is invisible to the docs and the RSS feed."""
    pages = {p.stem.lstrip("v") for p in (ROOT / "docs" / "releases").glob("v*.md")}
    current = current_version()
    assert current in pages, (
        f"v{current} shipped but docs/releases/v{current}.md does not exist, so the "
        f"release index cannot link it and the RSS feed cannot carry it."
    )


def test_capability_counts_match_the_registry():
    """The counts ROADMAP.md tells you to re-derive rather than edit.

    `ROADMAP.md` already carries the command that derives these and the note that
    they had "gone stale again by 2026-08-14, and again in the direction of
    understating what had shipped". A command you must remember to run is not a
    guard; this is. The registry import is pure, so this costs nothing.
    """
    from yazses.system import features as F

    total = len(F._CATEGORIES)
    planned = len(F._UNWIRED)
    wired = total - planned

    for relpath in ("ROADMAP.md", "docs/mobile/index.md"):
        text = (ROOT / relpath).read_text(encoding="utf-8")
        match = re.search(
            r"([0-9]+) capabilities[,)]?\s*\(?\*{0,2}([0-9]+) wired\s*/\s*([0-9]+)"
            r"|([0-9]+) capabilities, ([0-9]+) wired and ([0-9]+)",
            text,
        )
        assert match is not None, (
            f"{relpath} no longer states the capability counts in a recognised "
            f"form, so nothing is checking them. Fix the pattern, do not drop it."
        )
        got = tuple(int(g) for g in match.groups() if g is not None)
        assert got == (total, wired, planned), (
            f"{relpath} claims {got}, the registry says {(total, wired, planned)}. "
            f"Re-derive them; do not edit them by hand."
        )


def test_the_test_count_floor_is_still_true(request):
    """`ROADMAP.md`'s test figure is a floor, and this is what holds it up.

    An exact count cannot be guarded honestly: adding the tests in this very file
    moved the claim 4337 -> 4347 in one sitting, so any exact number is stale as
    soon as the suite grows. A floor inverts that -- it stays true as tests are
    added and only breaks when tests are *removed*, which is the direction that
    deserves a failure.

    The count comes from the **live session**, not a subprocess, so this costs
    nothing and cannot recurse. That makes it meaningless on a partial run (`-k`,
    one file), which `_is_full_run` detects from pytest's own options rather than
    from how many tests happened to be collected -- a test that cries wolf during
    ordinary development gets deleted.
    """
    collected = getattr(request.session, "testscollected", 0) or len(
        getattr(request.session, "items", [])
    )
    text = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
    match = re.search(r"\*\*([0-9][0-9,]*)\+ tests green\*\*", text)
    assert match is not None, (
        "ROADMAP.md no longer states a test floor in the `N+ tests green` form. "
        "Keep it a floor -- an exact count cannot be guarded (see the docstring)."
    )
    floor = int(match.group(1).replace(",", ""))

    # "Is this the whole suite?" must NOT be derived from the floor. Scaling the
    # threshold off `floor` conflates two unrelated questions, and it fails open in
    # the one case that matters: set the floor absurdly high and `collected` falls
    # below the scaled threshold, so the test *skips* instead of reporting the
    # claim it exists to check. Caught by red-green -- a floor of 9000 against 4348
    # collected passed silently. Asking pytest what was filtered keeps the two
    # decoupled and is exact, so a full run is recognised as one whatever the floor
    # says, and a genuinely shrunken suite fails rather than skips.
    if not _is_full_run(request.config):
        pytest.skip(
            f"filtered run ({collected} tests collected) -- the floor is only "
            f"meaningful for the whole suite"
        )
    assert collected >= floor, (
        f"ROADMAP.md claims {floor}+ tests, but the suite collected {collected}. "
        f"Tests were removed, or the floor was raised too far."
    )


def test_adr_range_matches_the_files_on_disk():
    """`adr-v2-001..NNN` must name an ADR that exists."""
    text = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
    match = re.search(r"ADRs `adr-v2-001\.\.([0-9]+)`", text)
    assert match is not None, "ROADMAP.md lost its ADR range claim"
    adrs = sorted(
        int(m.group(1))
        for p in (ROOT / "design" / "adr").iterdir()
        if (m := re.search(r"adr-v2-([0-9]+)", p.name))
    )
    assert adrs, "no v2 ADRs found -- this guard is checking nothing"
    assert int(match.group(1)) == adrs[-1], (
        f"ROADMAP.md claims ADRs up to {match.group(1)}, highest on disk is "
        f"{adrs[-1]}"
    )


def test_json_ld_in_the_home_page_still_parses():
    """A stale-version edit is the likeliest way to break this block silently."""
    text = (ROOT / "docs" / "index.md").read_text(encoding="utf-8")
    blocks = re.findall(
        r'<script type="application/ld\+json">(.*?)</script>', text, re.DOTALL
    )
    assert blocks, "the home page lost its JSON-LD block"
    for block in blocks:
        json.loads(block)


# --- the release index must link the pages that exist -----------------------


def _unlisted_releases(index_text: str, page_stems: set[str]) -> set[str]:
    """Release pages that exist on disk but are linked from nowhere in the index.

    Pure so the failure mode can be tested directly. A page nothing links to is
    reachable only by guessing its URL: it is in the sitemap and the RSS feed, and
    absent from the one page a reader opens to find it.
    """
    return {stem for stem in page_stems if f"{stem}.md" not in index_text}


def test_the_release_index_links_every_release_page() -> None:
    """`test_every_released_version_has_a_release_note_page` proves the page was
    written; nothing proved anyone could find it.

    The index is hand-maintained, and adding a release means editing it in two
    places — the "Current stable" paragraph *and* the list below. The first has a
    guard (above). The second did not, so a release could ship with a page that the
    index never mentions and no test would object.
    """
    index = ROOT / "docs" / "releases" / "index.md"
    text = index.read_text(encoding="utf-8")
    stems = {p.stem for p in (ROOT / "docs" / "releases").glob("v*.md")}
    assert stems, "no release note pages found — this guard is checking nothing"

    missing = _unlisted_releases(text, stems)
    assert not missing, (
        "release note pages exist that docs/releases/index.md never links, so a "
        f"reader cannot reach them from the releases page: {sorted(missing)}"
    )


def test_the_index_guard_notices_an_unlinked_page() -> None:
    """Red-green for the guard above, without mutating the repository.

    A guard that iterates is green on an empty set and green on a set it never
    compares; this pins that it actually reports a miss.
    """
    assert _unlisted_releases("- [v1.0.0](v1.0.0.md)", {"v1.0.0"}) == set()
    assert _unlisted_releases("- [v1.0.0](v1.0.0.md)", {"v1.0.0", "v1.1.0"}) == {"v1.1.0"}

class _Opt:
    """The pytest options `_is_full_run` reads, all defaulted to "not filtered"."""

    keyword = ""
    markexpr = ""
    deselect = None
    ignore = None
    lf = False
    failedfirst = False

    def __init__(self, **kw):
        self.file_or_dir = kw.pop("file_or_dir", ["tests"])
        for k, v in kw.items():
            setattr(self, k, v)


class _Config:
    def __init__(self, **kw):
        self.option = _Opt(**kw)


def test_a_whole_suite_run_is_recognised(tmp_path):
    """`make check` runs `pytest tests/ -q`, and bare `pytest` uses `testpaths`."""
    assert _is_full_run(_Config(file_or_dir=["tests"])) is True
    assert _is_full_run(_Config(file_or_dir=[])) is True


@pytest.mark.parametrize("kw", [
    {"keyword": "docs"},
    {"markexpr": "slow"},
    {"deselect": ["tests/test_x.py::test_y"]},
    {"ignore": ["tests/test_x.py"]},
    {"lf": True},
    {"failedfirst": True},
])
def test_every_way_of_removing_tests_counts_as_filtered(kw):
    """Each of these drops tests from the run, so the suite-wide floor says nothing.

    The regression this replaces: `-k "docs"` collected 1108 tests, cleared a fixed
    1000-test threshold, and then failed the 4300 floor.
    """
    assert _is_full_run(_Config(**kw)) is False


def test_naming_a_file_or_a_node_is_a_subset():
    assert _is_full_run(_Config(file_or_dir=["tests/test_docs_frontmatter.py"])) is False
    assert _is_full_run(_Config(file_or_dir=["tests/test_docs_frontmatter.py::test_x"])) is False


def test_a_directory_among_several_targets_is_still_whole():
    """Naming two directories is not a subset of either; naming one file is."""
    assert _is_full_run(_Config(file_or_dir=["tests", "tests"])) is True
    assert _is_full_run(_Config(file_or_dir=["tests", "tests/test_docs_frontmatter.py"])) is False


def test_the_verdict_cannot_consult_the_claimed_floor():
    """The earlier version's real point, kept.

    An absurd floor must make the check *fail*, not skip -- which requires that "is
    this the whole suite" be decided without reference to the floor. Asserted
    structurally rather than by grepping prose: the predicate takes `config` and
    nothing else, and its body reads no file, so there is no path by which the
    claimed number could reach it.
    """
    assert list(inspect.signature(_is_full_run).parameters) == ["config"]
    body = ast.parse(inspect.getsource(_is_full_run)).body[0].body
    reads = {
        getattr(n.func, "attr", getattr(n.func, "id", ""))
        for n in ast.walk(ast.Module(body=body[1:], type_ignores=[]))
        if isinstance(n, ast.Call)
    }
    assert not reads & {"read_text", "open", "search", "match"}, reads
