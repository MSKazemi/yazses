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
  elsewhere (the arm64 snap gap, the v2.21.0 desktop bundles): a claim nothing
  exercises reads exactly like a claim something does.

Both directions are checked here, for the classifiers and -- in the second half of
this file -- for the desktop bundle rows of `docs/platform-support.md`. Guarding
only the overstating direction is its own defect: this file did exactly that for
the bundles, and the result was a test that required the page to go on denying two
installers it had been shipping for 23 releases.

These are drift guards in the sense of `test_packaging_metadata.py` -- each one
compares a hand-written claim against a source of truth that a human does not
maintain by hand.
"""

from __future__ import annotations

import json
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


# --- desktop bundles: the page's marks must match what the release published ---
#
# The page's legend defines two marks that are claims of fact about a file:
# ✅ is "published and installable today" and ⏳ is "built by CI but not yet
# published". Only one thing can settle which applies -- whether the release
# carries the asset -- so that is what these tests compare against.
#
# **This guard used to read `experimental:` out of the build workflows instead,
# and enforced the wrong answer for 23 releases.** The reasoning was that
# `build-macos.yml` and `build-windows.yml` each mark their cross-architecture
# leg `experimental: true`, which sets `continue-on-error`, and a leg whose
# failure is invisible has not earned ✅. The premise is sound and the inference
# is not: continue-on-error says a failure would not be *noticed*, not that the
# build did not *happen*. Both legs went green on v2.22.0 and have attached an
# asset to every tag since, while this file required the page to keep saying "no
# release carries it yet" -- a test actively holding a documented falsehood in
# place, sending Intel Mac and Windows-on-ARM users to a slower install path for
# a file that was sitting on the release page.
#
# So the flag is deliberately no longer read here. It is a fact about CI policy
# and it belongs to `.github/CI_POLICY.md`; it is not evidence about what a user
# can download, and re-deriving availability from it would reintroduce the bug.
#
# The source of truth is `packaging/released-assets.json`: the asset list of the
# last release, written by `scripts/refresh-package-manifests.py` from the same
# `gh release view` call that produces every checksum in `packaging/`. The suite
# is offline by law (AGENTS.md rule 1) and may not query GitHub, so the fact is
# committed at the one moment it is known for certain and read from disk here.
# Its freshness is carried by the release flow that already reruns that script
# after every tag, and `--check` fails the release if the committed copy and the
# published assets disagree.
#
# The check is deliberately per-section and per-architecture: `arm64` is a
# shipped architecture under both macOS and Windows but `x86_64`/`x64` name
# different files, and a page-wide search cannot tell any of them apart.

RELEASED_ASSETS = ROOT / "packaging/released-assets.json"

#: workflow -> (page section, the word that must appear in the bundle column's
#: header, the asset name that section's `arch` values produce).
#:
#: The bundle column is the LAST one in each table, and the header word is
#: asserted so that reordering the table fails this guard loudly instead of
#: quietly checking `pipx` -- which is a different claim with a different truth.
#: The first version of this checked the whole row and tripped over the ✅ in the
#: pipx column, which is correct: `pipx install yazses` really does work on an
#: Intel Mac, whatever the .dmg does.
BUNDLE_WORKFLOWS = {
    ".github/workflows/build-macos.yml": (
        "## macOS",
        ".dmg",
        "YazSes-{version}-macos-{arch}.dmg",
    ),
    ".github/workflows/build-windows.yml": (
        "## Windows",
        ".exe",
        "YazSes-{version}-windows-{arch}.exe",
    ),
}

PLATFORM_PAGE = ROOT / "docs/platform-support.md"

#: The page's own legend, so the assertions below quote it rather than paraphrase.
AVAILABLE = "✅"
UNPUBLISHED = "⏳"


def _released() -> tuple[str, frozenset[str]]:
    """(version, every asset name) of the last release, as committed."""
    data = json.loads(RELEASED_ASSETS.read_text(encoding="utf-8"))
    return str(data["version"]), frozenset(data["assets"])


def _matrix_arches(relpath: str) -> list[str]:
    """Every `arch` the build workflow's matrix produces a bundle for."""
    workflow = yaml.safe_load((ROOT / relpath).read_text(encoding="utf-8"))
    (job,) = [j for j in workflow["jobs"].values() if "strategy" in j]
    return [str(entry["arch"]) for entry in job["strategy"]["matrix"]["include"]]


def _expected_asset(relpath: str, arch: str) -> str:
    version, _ = _released()
    return BUNDLE_WORKFLOWS[relpath][2].format(version=version, arch=arch)


def _published_bundles(relpath: str) -> dict[str, bool]:
    """arch -> did the last release actually attach that architecture's bundle."""
    _, released = _released()
    return {
        arch: _expected_asset(relpath, arch) in released
        for arch in _matrix_arches(relpath)
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


def test_the_released_asset_manifest_is_a_real_release():
    """Guard the guard: a placeholder here would make every case below a fiction."""
    version, released = _released()
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), (
        f"{RELEASED_ASSETS.name} declares version {version!r}, which is not a "
        f"release. Regenerate it with scripts/refresh-package-manifests.py."
    )
    assert released, f"{RELEASED_ASSETS.name} records no assets at all"
    assert any(version in name for name in released), (
        f"{RELEASED_ASSETS.name} says v{version} but not one of its {len(released)} "
        f"asset names carries that version: {sorted(released)}. The file is stale "
        f"or hand-edited."
    )


def test_every_bundle_matrix_maps_onto_a_released_asset_name():
    """Guard the guard, and the failure that would make this file lie quietly.

    Availability is read by *constructing* a filename from the matrix `arch` and
    looking it up. Rename the artefacts -- which has happened once already, when
    `YazSes-2.20.0.dmg` gained its `-macos-<arch>` suffix -- and every lookup
    misses, every architecture reads as unpublished, and the guard would then
    demand the page be rewritten to say nothing ships. Requiring at least one hit
    per workflow turns that into a loud failure here instead.
    """
    version, released = _released()
    for relpath in BUNDLE_WORKFLOWS:
        arches = _matrix_arches(relpath)
        assert len(arches) >= 2, f"{relpath} has no cross-architecture matrix"
        expected = {arch: _expected_asset(relpath, arch) for arch in arches}
        assert any(name in released for name in expected.values()), (
            f"{relpath}: not one of {sorted(expected.values())} is among the assets "
            f"v{version} published. Either the release shipped no desktop bundle at "
            f"all, or the naming changed and BUNDLE_WORKFLOWS still builds the old "
            f"filename -- fix the template before trusting any row below."
        )


def test_no_unpublished_bundle_is_documented_as_available():
    """The overstating direction, and the one that shipped first.

    A `continue-on-error` build leg fails without failing its workflow, so the run
    summary, the checks list and the release page all look normal while nothing was
    attached. That is not a hypothetical: on v2.21.0 both the macOS Intel and the
    Windows ARM legs failed and this page described them as built.
    """
    for relpath, (heading, word, _) in BUNDLE_WORKFLOWS.items():
        rows = _bundle_column(heading, word)
        for arch, published in _published_bundles(relpath).items():
            if published:
                continue
            cell = _bundle_cell(_row_for(arch, rows))
            assert AVAILABLE not in cell, (
                f"{heading.strip('# ')} {arch}: docs/platform-support.md marks the "
                f"bundle {AVAILABLE} ('published and installable today'), but "
                f"{_expected_asset(relpath, arch)} is not among the assets of the "
                f"last release recorded in {RELEASED_ASSETS.name}. There is nothing "
                f"to download.\n  {cell}"
            )


def test_every_published_bundle_is_documented_as_available():
    """The understating direction, and the one that actually shipped for longer.

    This page told Intel Mac and Windows-on-ARM users their installer did not exist
    yet through 23 consecutive releases that carried it, because the guard read the
    build leg's `experimental:` flag rather than the release. Understating support
    costs somebody a slower install path for a file that is already sitting there,
    which is the same class of harm as overstating it -- and a mark that says ⏳ is
    a factual claim ("not yet published"), not a hedge.
    """
    for relpath, (heading, word, _) in BUNDLE_WORKFLOWS.items():
        rows = _bundle_column(heading, word)
        for arch, published in _published_bundles(relpath).items():
            if not published:
                continue
            cell = _bundle_cell(_row_for(arch, rows))
            asset = _expected_asset(relpath, arch)
            assert AVAILABLE in cell, (
                f"{heading.strip('# ')} {arch}: the last release published {asset}, "
                f"but docs/platform-support.md does not mark the bundle "
                f"{AVAILABLE}.\n  {cell}"
            )
            assert UNPUBLISHED not in cell, (
                f"{heading.strip('# ')} {arch}: the page marks the bundle "
                f"{UNPUBLISHED} ('built by CI but not yet published') while the last "
                f"release published {asset}. Drop the mark and the prose around it — "
                f"a reader takes it as a reason to go and install something else."
                f"\n  {cell}"
            )
