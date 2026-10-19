#!/usr/bin/env python3
"""Map a pull request's changed paths to the CI scopes they need (#534).

This is the single, reviewable source of truth for "which change classes require which
CI lanes" that `.github/CI_POLICY.md` section 4 asks for. It classifies, and it makes the
one routing decision `test.yml` reads (#535): whether a change needs the full
cross-platform lane, or whether the always-on fast lane and Linux baseline are enough.
Which jobs make up each lane is the workflow's business, not this file's.

The rules are a fixed table of directory prefixes and paths, matched case-sensitively.
Nothing here runs git or opens a connection, so the same list of paths gives the same
answer on a laptop and on a GitHub runner, on any OS.

**Unknown means more validation, never less.** A path that no rule matches adds the
`unknown` scope, which requests the full gate. So does an empty change list — "nothing
changed" is more likely a broken diff step than a real PR.

A path may land in several scopes: `src/yazses/platform/macos/hotkey.py` is both
`python_core` and `macos`.

    git diff --name-only --no-renames origin/main...HEAD | python scripts/classify_changes.py
    python scripts/classify_changes.py docs/index.md src/yazses/cli.py
    git diff --name-only --no-renames "$BASE"...HEAD \
        | python scripts/classify_changes.py --github-output >> "$GITHUB_OUTPUT"

Always pass `--no-renames`. Without it, `git diff --name-only` lists only the new name of
a renamed file, so moving `src/x.py` to `docs/x.py` would classify as `docs_design` alone
and skip the runtime lanes. With it, the rename is listed as a deletion plus an addition,
and both paths are classified.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from fnmatch import fnmatchcase

DOCS_DESIGN = "docs_design"
PYTHON_CORE = "python_core"
TESTS = "tests"
ANDROID = "android"
MACOS = "macos"
WINDOWS = "windows"
PACKAGING = "packaging"
WORKFLOW_SECURITY = "workflow_security"
RELEASE = "release"
UNKNOWN = "unknown"

#: Every scope this script can emit, in output order.
SCOPES = (
    DOCS_DESIGN, PYTHON_CORE, TESTS, ANDROID, MACOS, WINDOWS,
    PACKAGING, WORKFLOW_SECURITY, RELEASE, UNKNOWN,
)

#: Scopes that do not need the full cross-platform lane. A change touching only these is
#: still validated by the fast lane and the whole suite on the Linux baseline leg, plus its
#: own path-filtered workflow (docs.yml's strict build, android-test.yml). Everything else,
#: and `unknown` above all, requests the full lane. Adding a scope here is a reviewed
#: decision to run *less* CI for it; `tests/test_ci_lanes.py` pins this set.
BASELINE_ONLY = frozenset({DOCS_DESIGN, ANDROID})

#: (pattern, scopes). A pattern ending in "/" matches everything under that directory;
#: any other pattern is an exact path or an `fnmatch` glob. Every matching rule
#: contributes its scopes — order does not matter and nothing short-circuits.
#:
#: Where a workflow already has a `paths:` filter, the matching rules here cover at
#: least those paths, so routing CI through this table can never run a lane on fewer
#: changes than it runs on today.
RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    # --- docs and design: the MkDocs site and its inputs (docs.yml `paths:`)
    ("docs/", (DOCS_DESIGN,)),
    ("design/", (DOCS_DESIGN,)),
    ("hooks/", (DOCS_DESIGN,)),  # MkDocs build hooks, see mkdocs.yml `hooks:`
    ("overrides/", (DOCS_DESIGN,)),  # MkDocs theme `custom_dir`
    ("mkdocs.yml", (DOCS_DESIGN,)),
    ("scripts/check-site-privacy.py", (DOCS_DESIGN,)),
    # --- Python runtime and its metadata
    ("src/", (PYTHON_CORE,)),
    # The project metadata feeds every build: docs.yml, build-macos.yml and
    # build-windows.yml all trigger on it, and it sets the version every package ships.
    ("pyproject.toml", (PYTHON_CORE, DOCS_DESIGN, MACOS, WINDOWS, PACKAGING)),
    ("uv.lock", (PYTHON_CORE, RELEASE)),  # dependabot-sbom.yml regenerates the SBOM from it
    # --- tests
    ("tests/", (TESTS,)),
    # --- Android, and the golden vectors it shares with the Python tests
    ("android/", (ANDROID,)),
    ("contract/", (ANDROID, PYTHON_CORE)),  # android-test.yml `paths:` includes it
    # --- macOS (build-macos.yml and macos-smoke.yml `paths:`)
    ("src/yazses/platform/macos/", (MACOS,)),
    ("src/yazses/system/intel_macos.py", (MACOS,)),
    ("src/yazses/__main__.py", (MACOS, WINDOWS)),  # the frozen app's entry point
    ("src/yazses/tray/", (MACOS, WINDOWS)),
    ("packaging/macos/", (MACOS,)),
    ("packaging/homebrew/", (MACOS,)),
    ("assets/yazses.icns", (MACOS,)),
    ("scripts/build-macos.sh", (MACOS, PACKAGING)),
    ("scripts/inspect-dmg.py", (MACOS, PACKAGING)),
    # --- Windows and MSIX (build-windows.yml and msix-validate.yml `paths:`)
    ("src/yazses/platform/windows/", (WINDOWS,)),
    ("src/yazses/system/wincon.py", (WINDOWS,)),
    ("src/yazses/system/winsetup.py", (WINDOWS,)),
    ("src/yazses/brandmark.py", (WINDOWS,)),
    ("packaging/windows/", (WINDOWS,)),
    ("packaging/store/", (WINDOWS,)),
    ("packaging/winget/", (WINDOWS,)),
    ("packaging/scoop/", (WINDOWS,)),
    ("packaging/chocolatey/", (WINDOWS,)),
    ("bucket/", (WINDOWS, PACKAGING)),  # the Scoop bucket manifest
    ("assets/", (WINDOWS, PACKAGING)),
    ("scripts/gen-icons.py", (WINDOWS, PACKAGING)),
    ("scripts/build-windows.ps1", (WINDOWS, PACKAGING)),
    ("scripts/build-msix.ps1", (WINDOWS, PACKAGING)),
    ("scripts/render-chocolatey.py", (WINDOWS, PACKAGING, RELEASE)),
    # --- packaging channels and installers
    ("packaging/", (PACKAGING,)),
    ("debian/", (PACKAGING,)),
    ("snap/", (PACKAGING,)),
    ("contrib/", (PACKAGING,)),  # systemd units, udev rules, .desktop files, completions
    ("flake.nix", (PACKAGING,)),
    ("flake.lock", (PACKAGING,)),
    ("install.sh", (PACKAGING,)),
    ("install-apt.sh", (PACKAGING,)),
    ("install-pipx.sh", (PACKAGING,)),
    ("scripts/build-deb.sh", (PACKAGING, RELEASE)),
    ("scripts/refresh-package-manifests.py", (PACKAGING, RELEASE)),
    # --- workflows and security configuration
    (".github/workflows/", (WORKFLOW_SECURITY,)),
    (".github/codeql/", (WORKFLOW_SECURITY,)),
    (".github/dependabot.yml", (WORKFLOW_SECURITY,)),
    (".github/CODEOWNERS", (WORKFLOW_SECURITY,)),
    (".github/CI_POLICY.md", (WORKFLOW_SECURITY,)),
    (".github/SECURITY.md", (WORKFLOW_SECURITY,)),
    (".github/labeler.yml", (WORKFLOW_SECURITY,)),
    ("scripts/check-action-pins.py", (WORKFLOW_SECURITY,)),
    # --- release and publishing
    (".github/release.yml", (RELEASE,)),
    ("CITATION.cff", (RELEASE,)),
    ("sbom.cdx.json", (RELEASE,)),
    ("packaging/released-assets.json", (RELEASE,)),
    ("scripts/patch-release-shas.sh", (RELEASE,)),
    ("scripts/verify-release-assets.py", (RELEASE,)),
    ("scripts/verify-provenance.py", (RELEASE,)),
    ("scripts/gen-sbom.py", (RELEASE,)),
    ("scripts/check-release-channels.py", (RELEASE, PACKAGING)),
    ("scripts/update-apt-repo.sh", (RELEASE, PACKAGING)),
    ("scripts/upload-ppa.sh", (RELEASE, PACKAGING)),
    # --- workflows that also belong to the lane they build or publish; each workflow
    # already lists itself in its own `paths:`, and labeler.yml labels the publishing
    # ones `packaging`
    (".github/workflows/docs.yml", (DOCS_DESIGN,)),
    (".github/workflows/eye-eval-ci.yml", (PYTHON_CORE, TESTS)),
    (".github/workflows/android-test.yml", (ANDROID,)),
    (".github/workflows/gradle-wrapper.yml", (ANDROID,)),
    (".github/workflows/build-macos.yml", (MACOS,)),
    (".github/workflows/macos-smoke.yml", (MACOS,)),
    (".github/workflows/build-windows.yml", (WINDOWS,)),
    (".github/workflows/msix-validate.yml", (WINDOWS,)),
    (".github/workflows/flatpak.yml", (PACKAGING,)),
    (".github/workflows/snap.yml", (PACKAGING, RELEASE)),
    (".github/workflows/docker.yml", (PACKAGING, RELEASE)),
    (".github/workflows/release.yml", (RELEASE, PACKAGING)),
    (".github/workflows/release-complete.yml", (RELEASE, PACKAGING)),
    (".github/workflows/publish-channels.yml", (RELEASE, PACKAGING)),
    (".github/workflows/apt-repo.yml", (RELEASE, PACKAGING)),
    (".github/workflows/ppa.yml", (RELEASE, PACKAGING)),
    (".github/workflows/channel-drift.yml", (RELEASE, PACKAGING)),
    (".github/workflows/checksums.yml", (RELEASE,)),
    (".github/workflows/dependabot-sbom.yml", (RELEASE,)),
)

#: Top-level directories that are deliberately left to the `unknown` fallback, with the
#: reason. Together with RULES this is the explicit decision for every top-level tree;
#: `tests/test_classify_changes.py` fails when a new one appears in neither. Moving an
#: entry from here into RULES is a reviewed decision to run *less* CI for it.
LEFT_UNKNOWN: dict[str, str] = {
    ".devcontainer": "development environment; affects how every lane's tooling resolves",
    "campaign": "task generator with generated files checked by the test suite",
    "data": "sample audio read by tests and benchmarks",
    "examples": "example configs validated by the test suite",
    "fuzz": "fuzz harnesses over the runtime text pipeline",
    "i18n": "localization glossary consumed by docs and runtime",
    "man": "generated from the CLI; a drift test guards it",
    "paper": "benchmark harness that is part of the lint gate",
}


def normalize(path: str) -> str:
    """Return `path` in the repository-relative, forward-slash form the rules expect."""
    path = path.strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path


def _matches(pattern: str, path: str) -> bool:
    if pattern.endswith("/"):
        return path.startswith(pattern)
    # fnmatchcase, not fnmatch: fnmatch folds case on Windows only, which would let the
    # same input classify differently on a Windows laptop and a Linux runner.
    return fnmatchcase(path, pattern)


def classify_path(path: str) -> set[str]:
    """Return the scopes of one repository-relative path; `{"unknown"}` if none match."""
    path = normalize(path)
    scopes = {scope for pattern, hits in RULES if _matches(pattern, path) for scope in hits}
    return scopes or {UNKNOWN}


def classify(paths: Iterable[str]) -> set[str]:
    """Return the union of scopes for a change set. An empty change set is `unknown`."""
    scopes: set[str] = set()
    seen_any = False
    for path in paths:
        if not normalize(path):
            continue
        seen_any = True
        scopes |= classify_path(path)
    return scopes if seen_any else {UNKNOWN}


def needs_full_lane(scopes: set[str]) -> bool:
    """True unless every scope is in BASELINE_ONLY. No scopes at all is a broken input,
    not a small change, so it requests the full lane too."""
    return not scopes or not scopes <= BASELINE_ONLY


def ordered(scopes: set[str]) -> list[str]:
    """Return `scopes` in the fixed SCOPES order, so output never depends on set order."""
    return [scope for scope in SCOPES if scope in scopes]


def github_output(scopes: set[str]) -> str:
    """Render `key=value` lines for `$GITHUB_OUTPUT`: one boolean per scope, the full-lane
    decision, and the list."""
    lines = [f"{scope}={'true' if scope in scopes else 'false'}" for scope in SCOPES]
    lines.append(f"full={'true' if needs_full_lane(scopes) else 'false'}")
    lines.append(f"scopes={json.dumps(ordered(scopes))}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "paths", nargs="*",
        help="changed paths; read one per line from stdin when none are given",
    )
    parser.add_argument(
        "--github-output", action="store_true",
        help="print key=value lines for $GITHUB_OUTPUT instead of JSON",
    )
    args = parser.parse_args(argv)

    paths = args.paths if args.paths else sys.stdin.read().splitlines()
    scopes = classify(paths)
    if args.github_output:
        sys.stdout.write(github_output(scopes))
    else:
        print(json.dumps({"scopes": ordered(scopes), "full": needs_full_lane(scopes)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
