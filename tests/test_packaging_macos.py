"""Guards on the macOS packaging artefacts.

These files are never exercised by the test suite the way `src/` is -- the .app is
built by PyInstaller on a macOS runner and the cask is consumed by Homebrew, so
neither is imported here and both drifted silently for a long time:

* `packaging/macos/yazses.spec` hardcoded ``CFBundleVersion = "0.1.2"``. Every
  .dmg from v0.1.3 through v2.18.0 shipped an .app that told macOS it was
  version 0.1.2, so an upgrade read as a downgrade.
* `packaging/homebrew/yazses.rb` sat at v2.17.0 with v2.17.0's checksum while
  v2.18.0 was the current release, and carried no architecture constraint even
  though the .dmg is arm64-only.

The checks below are deliberately offline and content-based: they parse the two
files as text/TOML and never download an asset, so they are cheap enough to run
in ordinary CI on every platform.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SPEC = REPO / "packaging" / "macos" / "yazses.spec"
CASK = REPO / "packaging" / "homebrew" / "yazses.rb"


@pytest.fixture(scope="module")
def spec_text() -> str:
    return SPEC.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def cask_text() -> str:
    return CASK.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def project_version() -> str:
    data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


# --------------------------------------------------------------------------
# yazses.spec
# --------------------------------------------------------------------------


def test_spec_derives_version_from_pyproject(spec_text: str) -> None:
    """CFBundle* must be derived, never a literal.

    A literal is what produced the 0.1.2 bug: it cannot be caught by reading the
    spec, only by inspecting a built .app on a Mac, which nobody does.
    """
    assert '"CFBundleVersion": VERSION' in spec_text
    assert '"CFBundleShortVersionString": VERSION' in spec_text

    # And the derivation actually reads pyproject.
    assert "tomllib" in spec_text
    assert 'pyproject.toml' in spec_text


def test_spec_version_expression_evaluates_to_project_version(
    spec_text: str, project_version: str
) -> None:
    """Execute the spec's own version lookup and compare to pyproject.

    Guards against the derivation being present but pointed at the wrong key --
    e.g. ``["tool"]["poetry"]["version"]`` on a PEP 621 project.
    """
    match = re.search(
        r"^VERSION = (tomllib\.loads\(.*?\))\[.*?\]$",
        spec_text,
        re.M | re.S,
    )
    assert match is not None, "no recognisable VERSION = tomllib.loads(...) assignment"

    namespace: dict[str, object] = {"tomllib": tomllib, "REPO": REPO}
    exec(f"VERSION = {match.group(0).split('=', 1)[1].strip()}", namespace)  # noqa: S102
    assert namespace["VERSION"] == project_version


def test_spec_target_arch_and_cask_arch_agree(
    spec_text: str, cask_text: str
) -> None:
    """The build's architecture and the cask's `depends_on arch:` are one fact.

    Asserted against the actual ``target_arch`` value rather than the surrounding
    prose, so the two can only ever move together:

    * ``target_arch=None`` -- host arch. CI's host is the arm64 ``macos-latest``
      image, so the cask must restrict to ``:arm64``.
    * ``target_arch="universal2"`` -- both slices present, so the cask must drop
      the restriction. (Reaching this also requires universal2 wheels for every
      native dependency; ``ctranslate2`` ships separate arm64/x86_64 wheels, so
      flipping the value alone will fail the build, not fix Intel.)

    Whoever pays for an Intel runner will land here, and the failure message is
    the checklist for what else has to change.
    """
    match = re.search(r"^\s*target_arch=([^,]+),", spec_text, re.M)
    assert match is not None, "no target_arch= in the EXE() block"
    target_arch = match.group(1).strip()

    cask_is_arm64_only = bool(
        re.search(r"^\s*depends_on\s+arch:\s*:arm64", cask_text, re.M)
    )

    if target_arch == "None":
        assert cask_is_arm64_only, (
            "yazses.spec builds host-arch (target_arch=None) on the arm64 "
            "macos-latest runner, so the .dmg has no x86_64 slice, but the cask "
            "does not declare `depends_on arch: :arm64`. Intel users would "
            "install an app that cannot launch."
        )
    elif target_arch.strip("\"'") == "universal2":
        assert not cask_is_arm64_only, (
            "yazses.spec now targets universal2, so the cask's "
            "`depends_on arch: :arm64` wrongly locks Intel users out. Also "
            "update docs/macos-install.md, which currently sends them to pipx."
        )
    else:
        pytest.fail(
            f"unrecognised target_arch={target_arch!r}; teach this test what it "
            "means for the cask's architecture constraint"
        )


def test_spec_minimum_system_version_matches_cask(
    spec_text: str, cask_text: str
) -> None:
    """LSMinimumSystemVersion and `depends_on macos:` must agree.

    The cask already carried a comment asking a human to keep these in step;
    this is that comment made enforceable.
    """
    spec_min = re.search(r'"LSMinimumSystemVersion":\s*"([\d.]+)"', spec_text)
    assert spec_min is not None
    cask_min = re.search(r"depends_on\s+macos:\s*\">=\s*:(\w+)\"", cask_text)
    assert cask_min is not None

    macos_names = {"11.0": "big_sur", "12.0": "monterey", "13.0": "ventura"}
    expected = macos_names.get(spec_min.group(1))
    assert expected is not None, (
        f"unmapped LSMinimumSystemVersion {spec_min.group(1)!r}; extend macos_names"
    )
    assert cask_min.group(1) == expected


# --------------------------------------------------------------------------
# yazses.rb (the Homebrew cask)
# --------------------------------------------------------------------------


def test_cask_sha256_is_a_real_digest(cask_text: str) -> None:
    """No PLACEHOLDER_… checksums.

    Two sibling .rb files in this directory still carry placeholders; they are
    kept only as history and must never be what ships.
    """
    match = re.search(r'^\s*sha256\s+"([^"]+)"', cask_text, re.M)
    assert match is not None
    digest = match.group(1)
    assert re.fullmatch(r"[0-9a-f]{64}", digest), (
        f"cask sha256 is not a 64-char hex digest: {digest!r}"
    )


def test_cask_url_interpolates_version(cask_text: str) -> None:
    """The URL must be built from `version`, so the two cannot diverge."""
    match = re.search(r"^\s*url\s+\"([^\"]+)\"", cask_text, re.M)
    assert match is not None
    url = match.group(1)
    assert "#{version}" in url, f"cask url hardcodes a version: {url!r}"


def test_cask_declares_arm64_only(cask_text: str) -> None:
    """The .dmg has no x86_64 slice, so the cask must refuse on Intel.

    Without this, `brew install --cask yazses` on an Intel Mac succeeds and then
    the app silently fails to launch. See packaging/README.md.
    """
    assert re.search(r"^\s*depends_on\s+arch:\s*:arm64", cask_text, re.M), (
        "cask must declare `depends_on arch: :arm64` while the .dmg is built "
        "host-arch on the arm64 macos-latest runner"
    )


def test_cask_points_intel_users_somewhere_that_works(cask_text: str) -> None:
    """Refusing to install is only half an answer; give them the working route."""
    caveats = cask_text.split("caveats", 1)
    assert len(caveats) == 2, "cask has no caveats block"
    assert "pipx install yazses" in caveats[1]


def test_only_one_publishable_cask(cask_text: str) -> None:
    """The two v1.0 Rust-era .rb files must stay unpublishable.

    They describe releases that were never cut and still hold placeholder
    checksums; publishing one would 404 for every user.
    """
    for stale in ("yazses-formula.rb", "yazses-v1.rb"):
        path = CASK.parent / stale
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        assert "PLACEHOLDER" in text, (
            f"{stale} no longer looks like an abandoned artefact -- if it became "
            "real, update this test and packaging/README.md"
        )


# ---- Version metadata ----------------------------------------------------


def test_spec_bundles_package_metadata(spec_text: str) -> None:
    """The .app shipped with no .dist-info, so it could not name its own version.

    PyInstaller bundles no package metadata unless the spec asks for it, and
    ``importlib.metadata.version("yazses")`` backs ``--version``, the About box,
    ``doctor``, the updater and the diagnostic report. Inside the frozen bundle
    every one of them met ``PackageNotFoundError``.

    The Windows spec has had this line -- and ``test_packaging_windows.py``'s
    identical guard -- since the installer smoke test caught it there. macOS got
    neither, which is a guard existing on one platform and not its twin. It
    surfaced when the first human to run the macOS build on real hardware pasted
    ``[WARN] Version: yazses version metadata not found`` into #182.
    """
    assert "copy_metadata" in spec_text
    assert 'copy_metadata("yazses")' in spec_text
