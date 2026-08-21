"""The platform and interpreter claims must match what CI actually proves.

`pyproject.toml`'s classifiers are not decoration. PyPI renders them as the
project's own answer to "does this run on my Python, on my OS?", and the tools
that consume them -- distro packagers, `pip index`, dependency dashboards, the
PyPI sidebar -- never read the CI matrix or `docs/platform-support.md`. So a
classifier list that drifts from reality is a wrong answer delivered to exactly
the people who cannot check it.

It drifts in both directions and both are defects:

* **Understating** hides support that exists. The matrix has proven 3.13 and 3.14
  on every push since they were added, while the classifiers still said 3.11 and
  3.12 -- so a packager filtering on `Programming Language :: Python :: 3.13`
  concluded YazSes did not support an interpreter it had been green on for weeks.
* **Overstating** is the failure mode this project has already been bitten by
  elsewhere (the arm64 snap gap, the Windows-ARM row): a claim nothing exercises
  reads exactly like a claim something does.

These are drift guards in the sense of `test_packaging_metadata.py` -- each one
compares a hand-written classifier against a source of truth that a human does
not maintain by hand.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
CLASSIFIERS: list[str] = PYPROJECT["project"]["classifiers"]
REQUIRES_PYTHON: str = PYPROJECT["project"]["requires-python"]

WORKFLOW = ROOT / ".github/workflows/test.yml"

_VERSION_CLASSIFIER = re.compile(r"^Programming Language :: Python :: (\d+\.\d+)$")


def _tested_python_versions() -> set[str]:
    """Every interpreter the `test` job runs the suite on.

    Reads both the matrix axis and its `include:` additions -- 3.13 and 3.14 are
    single-OS `include` entries, so reading only `python-version` would miss the
    exact versions most likely to be missing a classifier.
    """
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    matrix = workflow["jobs"]["test"]["strategy"]["matrix"]
    versions = {str(v) for v in matrix.get("python-version", [])}
    for entry in matrix.get("include", []):
        if "python-version" in entry:
            versions.add(str(entry["python-version"]))
    return versions


def _classified_python_versions() -> set[str]:
    return {
        m.group(1)
        for c in CLASSIFIERS
        if (m := _VERSION_CLASSIFIER.match(c))
    }


def _as_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def test_ci_actually_tests_some_python_versions():
    """Guard the guard: a parse failure must not look like agreement."""
    assert _tested_python_versions(), f"no python versions parsed out of {WORKFLOW}"


def test_every_python_version_ci_proves_has_a_classifier():
    """Support that is proven but unclaimed is support nobody can discover."""
    missing = _tested_python_versions() - _classified_python_versions()
    assert not missing, (
        f"CI proves Python {sorted(missing)} but pyproject.toml claims no classifier "
        f"for them. Add 'Programming Language :: Python :: X.Y' for each."
    )


def test_no_python_classifier_claims_a_version_ci_never_runs():
    """The reverse drift: a claim with nothing behind it."""
    unproven = _classified_python_versions() - _tested_python_versions()
    assert not unproven, (
        f"pyproject.toml claims Python {sorted(unproven)} but the test matrix in "
        f"{WORKFLOW.name} never runs it. Either test it or drop the classifier."
    )


def test_requires_python_floor_is_the_lowest_version_ci_proves():
    """`>=3.11` and a matrix starting at 3.12 would strand real installs."""
    floor = re.match(r">=\s*(\d+\.\d+)", REQUIRES_PYTHON)
    assert floor, f"cannot read a floor out of requires-python={REQUIRES_PYTHON!r}"
    lowest_tested = min(_tested_python_versions(), key=_as_tuple)
    assert floor.group(1) == lowest_tested, (
        f"requires-python allows {floor.group(1)} but the lowest interpreter CI runs "
        f"is {lowest_tested}. Users on {floor.group(1)} install a version nothing tests."
    )


def test_bsd_is_not_claimed_as_a_supported_operating_system():
    """BSD ships a real backend and still must not carry an OS classifier.

    `src/yazses/platform/bsd/` exists, `platform/factory.py` dispatches to it, and
    the unit suite exercises it against a simulated `sys.platform`. None of that
    makes `pip install yazses` work on a BSD: `ctranslate2` publishes 35 wheels and
    **no sdist**, and there is no port, so resolution fails before any YazSes code
    is reached (issue #306, and the failure box in `docs/platform-support.md`).

    An `Operating System :: POSIX :: BSD` classifier would tell every packaging tool
    that the install works. It does not. This test exists so the classifier is not
    added as an obvious-looking tidy-up: **it becomes correct only when the install
    does**, which means moving the Whisper stack behind an extra, not editing this
    list.
    """
    bsd = [c for c in CLASSIFIERS if "BSD" in c and c.startswith("Operating System")]
    assert not bsd, (
        f"{bsd} claims BSD installs work. It does not -- ctranslate2 has no BSD "
        f"wheel and no sdist (#306). Fix the install before making the claim."
    )


def test_every_os_with_a_backend_that_can_install_is_classified():
    """Linux, macOS and Windows all dispatch in factory.py and all install."""
    joined = " ".join(CLASSIFIERS)
    for token in ("POSIX :: Linux", "MacOS", "Microsoft :: Windows"):
        assert token in joined, f"no Operating System classifier mentioning {token!r}"


# --- desktop bundles: an advisory build leg must not read as a shipped one -----
#
# `build-macos.yml` and `build-windows.yml` each carry a cross-architecture leg
# marked `experimental: true`, which sets `continue-on-error` on it. That is the
# right call -- a brand-new cross-arch job must not be able to fail a release the
# primary architecture completed fine -- but it has a consequence that has now
# bitten this repository twice:
#
#   **A failing advisory leg reports the workflow as successful.** Nothing in the
#   run summary, the release, or the checks list says the architecture was not
#   built. The FreeBSD job spent weeks failing before a single test ran while
#   reporting success; on v2.21.0 both the macOS Intel and Windows ARM legs failed
#   and the page still described them as built.
#
# So the page may describe an experimental leg as *attempted*, never as *available*.
# The ✅ mark is defined there as "published and installable today", and no leg
# whose failure is invisible has earned it.
#
# The check is deliberately per-section: `arm64` is a shipped architecture under
# macOS and an unshipped one under Windows, and a page-wide search cannot tell
# those apart.

#: workflow -> (page section, the word that must appear in the bundle column's
#: header). The bundle column is the LAST one in each table, and the header word
#: is asserted so that reordering the table fails this guard loudly instead of
#: quietly checking `pipx` -- which is a different claim with a different truth.
#: The first version of this checked the whole row and tripped over the ✅ in the
#: pipx column, which is correct: `pipx install yazses` really does work on an
#: Intel Mac. It is the .dmg that does not exist.
BUNDLE_WORKFLOWS = {
    ".github/workflows/build-macos.yml": ("## macOS", ".dmg"),
    ".github/workflows/build-windows.yml": ("## Windows", ".exe"),
}

PLATFORM_PAGE = ROOT / "docs/platform-support.md"


def _bundle_matrix(relpath: str) -> dict[str, bool]:
    """arch -> is it an advisory (continue-on-error) leg."""
    workflow = yaml.safe_load((ROOT / relpath).read_text(encoding="utf-8"))
    (job,) = [j for j in workflow["jobs"].values() if "strategy" in j]
    return {
        str(entry["arch"]): bool(entry.get("experimental", False))
        for entry in job["strategy"]["matrix"]["include"]
    }


def _section_rows(heading: str) -> list[str]:
    """The markdown table rows under one `##` heading of the platform page."""
    text = PLATFORM_PAGE.read_text(encoding="utf-8")
    start = text.index(heading) + len(heading)
    rest = text[start:]
    end = rest.find("\n## ")
    body = rest if end == -1 else rest[:end]
    return [line for line in body.splitlines() if line.startswith("|")]


def _row_for(arch: str, rows: list[str]) -> str:
    # Matched against the **CPU column only**, not the whole row. The macOS Intel
    # row reads "❌ cask tracks arm64" in its Homebrew cell, so a whole-row search
    # for `arm64` finds two rows and picks the wrong one -- which is how the first
    # version of this guard failed.
    matches = [r for r in rows if arch in r.split("|")[1]]
    assert len(matches) == 1, (
        f"expected exactly one table row mentioning {arch!r}, found {len(matches)}: "
        f"{matches}. The page's shape changed, so this guard is no longer reading "
        f"what it thinks it is."
    )
    return matches[0]


def _bundle_cell(row: str) -> str:
    cells = [c for c in row.split("|") if c.strip()]
    return cells[-1]


def _bundle_column(heading: str, header_word: str) -> list[str]:
    """The bundle column's cells, header first, for one page section."""
    rows = _section_rows(heading)
    assert len(rows) >= 3, f"{heading}: expected a table with rows, got {rows}"
    header = _bundle_cell(rows[0])
    assert header_word in header, (
        f"{heading}: the last table column is {header!r}, which does not look "
        f"like the {header_word} bundle. The columns were reordered, so this "
        f"guard would be reading the wrong claim."
    )
    return rows


def test_the_bundle_matrices_are_readable():
    """Guard the guard: an unparsed matrix would make every case below vacuous."""
    for relpath in BUNDLE_WORKFLOWS:
        matrix = _bundle_matrix(relpath)
        assert len(matrix) >= 2, f"{relpath} has no cross-architecture matrix"
        assert any(matrix.values()), f"{relpath} marks no leg experimental"
        assert not all(matrix.values()), f"{relpath} marks every leg experimental"


def test_no_advisory_build_leg_is_documented_as_available():
    """The overstating direction, and the one that shipped."""
    for relpath, (heading, word) in BUNDLE_WORKFLOWS.items():
        rows = _bundle_column(heading, word)
        for arch, experimental in _bundle_matrix(relpath).items():
            if not experimental:
                continue
            cell = _bundle_cell(_row_for(arch, rows))
            assert "✅" not in cell, (
                f"{heading.strip('# ')} {arch}: docs/platform-support.md marks the "
                f"bundle ✅ ('published and installable today'), but its build leg "
                f"in {relpath} is `experimental: true` -- continue-on-error, so a "
                f"failure there reports the workflow as green and ships nothing. "
                f"Promote the leg first, then the row.\n  {cell}"
            )


def test_every_proven_build_leg_is_documented_as_available():
    """The understating direction. A blocking leg that has to pass for the release
    to exist is exactly the evidence ✅ is meant to record; leaving it at ⏳ sends
    people to a slower install path for no reason."""
    for relpath, (heading, word) in BUNDLE_WORKFLOWS.items():
        rows = _bundle_column(heading, word)
        for arch, experimental in _bundle_matrix(relpath).items():
            if experimental:
                continue
            cell = _bundle_cell(_row_for(arch, rows))
            assert "✅" in cell, (
                f"{heading.strip('# ')} {arch}: its build leg in {relpath} is "
                f"blocking -- the release cannot be cut without it -- but the page "
                f"does not mark the bundle ✅.\n  {cell}"
            )
