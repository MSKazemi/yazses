"""The change classifier's table is pinned here, because a wrong rule fails silently (#534).

`scripts/classify_changes.py` decides which CI scopes a pull request touches. A rule that
stops matching does not turn anything red: the lane it fed just stops running, and the PR
goes green on less evidence than before. Every test below makes that silent failure loud.

Three kinds of check:

- **the mapping**: one representative path per top-level area, compared exactly, so a
  scope gained or lost shows up in review as a changed line in a table here;
- **the fail-safe**: anything unmatched, empty or misspelled requests the full gate;
- **the guards that keep the table honest as the repository moves**: every tracked
  top-level directory has a decision, every rule still matches a tracked file, and every
  workflow with a `pull_request` paths filter is covered by the scope its lane will be
  routed by.

Scope names are written out as strings rather than read from the module. Workflows will
key on these exact names, so renaming one has to fail a test, not pass one.
"""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tests.gitprobe import require_git

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "classify_changes.py"
WORKFLOWS = ROOT / ".github" / "workflows"


def _load():
    """Load the script as a module; `scripts/` is not a package, so it cannot be imported."""
    spec = importlib.util.spec_from_file_location("classify_changes", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


classifier = _load()

#: One representative path per top-level area, with the exact scopes it must produce.
#: Exact rather than "contains": a rule that starts adding a scope is as much a routing
#: change as one that stops, and both should be a reviewed line in this table.
AREAS = [
    ("docs/index.md", {"docs_design"}),
    ("design/README.md", {"docs_design"}),
    ("hooks/design_tier.py", {"docs_design"}),
    ("overrides/home.html", {"docs_design"}),
    ("mkdocs.yml", {"docs_design"}),
    ("src/yazses/cli.py", {"python_core"}),
    ("tests/test_classify_changes.py", {"tests"}),
    ("android/README.md", {"android"}),
    ("packaging/macos/entitlements.plist", {"macos", "packaging"}),
    ("packaging/homebrew/yazses-formula.rb", {"macos", "packaging"}),
    ("packaging/windows/msix/AppxManifest.xml", {"windows", "packaging"}),
    ("packaging/store/README.md", {"windows", "packaging"}),
    ("bucket/yazses.json", {"windows", "packaging"}),
    ("packaging/flatpak/README.md", {"packaging"}),
    ("debian/changelog", {"packaging"}),
    ("snap/snapcraft.yaml", {"packaging"}),
    ("contrib/60-yazses-uinput.rules", {"packaging"}),
    ("flake.nix", {"packaging"}),
    ("flake.lock", {"packaging"}),
    ("install.sh", {"packaging"}),
    ("install-apt.sh", {"packaging"}),
    ("install-pipx.sh", {"packaging"}),
    (".github/workflows/test.yml", {"workflow_security"}),
    (".github/codeql/codeql-config.yml", {"workflow_security"}),
    (".github/dependabot.yml", {"workflow_security"}),
    ("scripts/classify_changes.py", {"workflow_security"}),
    ("scripts/ci_gate.py", {"workflow_security"}),
    (".github/release.yml", {"release"}),
    ("CITATION.cff", {"release"}),
    ("sbom.cdx.json", {"release"}),
]

#: Files that sit in more than one lane. The two halves of each answer come from
#: different rules, so these catch a rule that is deleted while a broader one still
#: matches: `src/yazses/platform/macos/` losing `macos` would still be `python_core`,
#: never `unknown`, and nothing else would notice.
CROSS_CUTTING = [
    ("src/yazses/platform/macos/__init__.py", {"python_core", "macos"}),
    ("src/yazses/platform/windows/__init__.py", {"python_core", "windows"}),
    ("src/yazses/tray/__init__.py", {"python_core", "macos", "windows"}),
    ("src/yazses/__main__.py", {"python_core", "macos", "windows"}),
    ("contract/README.md", {"android", "python_core"}),
    ("assets/yazses.icns", {"macos", "windows", "packaging"}),
    ("scripts/render-chocolatey.py", {"windows", "packaging", "release"}),
    ("uv.lock", {"python_core", "release"}),
    ("pyproject.toml", {"docs_design", "python_core", "macos", "windows", "packaging"}),
    (".github/workflows/docs.yml", {"workflow_security", "docs_design"}),
    (".github/workflows/release.yml", {"workflow_security", "release", "packaging"}),
]

#: Paths no rule claims, outside the trees in `LEFT_UNKNOWN` (which have their own test):
#: root files, a script without a rule, a `.github/` file that is not workflow config,
#: and a tree that does not exist yet.
UNCLAIMED = [
    "README.md",
    "CHANGELOG.md",
    "AGENTS.md",
    "Makefile",
    ".gitignore",
    "scripts/gen-docs.py",
    ".github/PULL_REQUEST_TEMPLATE.md",
    "a-tree-that-does-not-exist-yet/main.py",
]

#: The scopes each path-filtered `pull_request` workflow will be routed by: it runs when
#: any of them is set. The classifier promises its rules cover at least each workflow's own
#: `paths:` filter, so routing the workflow by these scopes instead can never run it on
#: fewer changes than it runs on today.
LANES = {
    "android-test.yml": {"android"},
    "build-macos.yml": {"macos"},
    "build-windows.yml": {"windows"},
    "docs.yml": {"docs_design"},
    # Its filter spans the eye-evaluation code, its tests and fixtures, and scripts that
    # no rule claims; there is no eye-tracking scope, so it rides on the two it touches.
    "eye-eval-ci.yml": {"python_core", "tests"},
    "flatpak.yml": {"packaging"},
    "macos-smoke.yml": {"macos"},
    "msix-validate.yml": {"windows"},
}


@pytest.fixture(scope="module")
def tracked() -> list[str]:
    """Every path git tracks. The working tree also holds `.venv`, caches and build
    output, none of which a pull request can change. `-z` because without it git quotes
    any path with a non-ASCII character, and the quoted form matches no rule."""
    require_git()
    listing = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout
    return [path for path in listing.split("\0") if path]


def _pull_request_paths(workflow: Path) -> list[str] | None:
    """The workflow's `on.pull_request.paths`, or None when it has no such filter."""
    doc = yaml.safe_load(workflow.read_text(encoding="utf-8")) or {}
    # YAML 1.1 parses the key on: as boolean True.
    triggers = doc.get(True, doc.get("on")) or {}
    event = triggers.get("pull_request") if isinstance(triggers, dict) else None
    return event.get("paths") if isinstance(event, dict) else None


# --- the mapping


def test_the_scope_names_are_the_ones_workflows_will_read() -> None:
    """Workflows read these as `steps.<id>.outputs.<scope>`. A renamed scope makes
    that expression empty, which reads as false and skips the lane, so the names and
    their output order are part of the contract."""
    assert classifier.SCOPES == (
        "docs_design",
        "python_core",
        "tests",
        "android",
        "macos",
        "windows",
        "packaging",
        "workflow_security",
        "release",
        "unknown",
    )


@pytest.mark.parametrize(("path", "scopes"), AREAS, ids=[path for path, _ in AREAS])
def test_each_area_classifies_to_its_scopes(path: str, scopes: set[str]) -> None:
    assert classifier.classify_path(path) == scopes


@pytest.mark.parametrize(
    ("path", "scopes"), CROSS_CUTTING, ids=[path for path, _ in CROSS_CUTTING]
)
def test_a_cross_cutting_file_lands_in_every_lane_it_affects(
    path: str, scopes: set[str]
) -> None:
    assert classifier.classify_path(path) == scopes


# --- the fail-safe


@pytest.mark.parametrize("path", UNCLAIMED)
def test_an_unclaimed_path_requests_the_full_gate(path: str) -> None:
    assert classifier.classify_path(path) == {"unknown"}


@pytest.mark.parametrize("tree", sorted(classifier.LEFT_UNKNOWN))
def test_a_tree_left_unknown_is_not_claimed_by_any_rule(tree: str) -> None:
    """`LEFT_UNKNOWN` says these trees get the full gate. A rule that later matches one
    would quietly make that entry false, and its stated reason with it."""
    assert classifier.classify_path(f"{tree}/any/file") == {"unknown"}


def test_an_unknown_path_is_not_absorbed_by_known_ones() -> None:
    """One unclassified file in an otherwise docs-only PR still requests the full gate."""
    assert classifier.classify(["docs/index.md", "README.md"]) == {"docs_design", "unknown"}


@pytest.mark.parametrize(
    "paths", [[], [""], ["", "   ", "\t"]], ids=["nothing", "one-blank", "only-blanks"]
)
def test_an_empty_change_set_requests_the_full_gate(paths: list[str]) -> None:
    """No changed paths is far more likely a broken diff step than a real PR."""
    assert classifier.classify(paths) == {"unknown"}


@pytest.mark.parametrize(
    "spelling",
    ["src\\yazses\\cli.py", "./src/yazses/cli.py", "././src/yazses/cli.py", " src/yazses/cli.py\r"],
    ids=["backslashes", "dot-slash", "repeated-dot-slash", "whitespace-and-cr"],
)
def test_spellings_of_one_path_classify_the_same(spelling: str) -> None:
    """A Windows shell, a `./`-prefixed list and a CRLF file are all the same change."""
    assert classifier.classify_path(spelling) == {"python_core"}


@pytest.mark.parametrize(
    "path", ["Docs/index.md", "SRC/yazses/cli.py", "docsite/index.md", "srcs/yazses/cli.py"]
)
def test_near_misses_do_not_match(path: str) -> None:
    """Matching is case-sensitive on every OS, as git paths are, and a directory rule
    matches only at a `/` boundary. Each near miss is `unknown`, the safe way to be wrong."""
    assert classifier.classify_path(path) == {"unknown"}


def test_the_answer_does_not_depend_on_input_order() -> None:
    """`git diff` lists paths in its own order; the scopes must not depend on it."""
    paths = [path for path, _ in AREAS + CROSS_CUTTING]
    assert classifier.classify(reversed(paths)) == classifier.classify(paths)


def test_output_order_is_the_scopes_order_not_set_order() -> None:
    """Sets have no stable order across runs, so output follows `SCOPES` instead."""
    assert classifier.ordered({"unknown", "release", "docs_design"}) == [
        "docs_design",
        "release",
        "unknown",
    ]


# --- the guards that keep the table honest


def test_every_top_level_directory_has_a_classification_decision(tracked: list[str]) -> None:
    """A new top-level tree must be routed by a rule or listed in `LEFT_UNKNOWN` with a
    reason. Its files would fall to `unknown` either way, which is safe; the point is that
    nobody gets to add a tree without deciding which lanes it needs."""
    tops = {path.split("/", 1)[0] for path in tracked if "/" in path}
    # Guard the guard: an empty listing would make the check below vacuous.
    assert len(tops) >= 15, f"only {len(tops)} top-level directories found; the listing is wrong"
    decided = {pattern.split("/", 1)[0] for pattern, _ in classifier.RULES if "/" in pattern}
    undecided = sorted(tops - decided - set(classifier.LEFT_UNKNOWN))
    assert not undecided, (
        f"top-level directories with no classification decision: {undecided}. Add rules "
        f"for them to RULES in scripts/classify_changes.py, or list them in LEFT_UNKNOWN "
        f"with the reason they need the full gate."
    )


def test_every_left_unknown_entry_still_exists(tracked: list[str]) -> None:
    """An entry for a tree that is gone documents a decision about nothing."""
    tops = {path.split("/", 1)[0] for path in tracked if "/" in path}
    stale = sorted(set(classifier.LEFT_UNKNOWN) - tops)
    assert not stale, f"LEFT_UNKNOWN lists directories that are no longer tracked: {stale}"


def test_every_rule_still_matches_a_tracked_path(tracked: list[str]) -> None:
    """A renamed file leaves its rule behind, matching nothing. The new name is not always
    `unknown`: rename `src/yazses/system/wincon.py` and it is still `python_core` under
    `src/`, but no longer `windows`, so the Windows lane stops seeing it."""
    dead = [
        pattern
        for pattern, _ in classifier.RULES
        if not any(classifier._matches(pattern, path) for path in tracked)
    ]
    assert not dead, f"rules in scripts/classify_changes.py that match no tracked path: {dead}"


def test_every_path_filtered_workflow_has_a_lane() -> None:
    """A new path-filtered workflow needs its scopes in LANES before the test below can
    check that the classifier covers its filter."""
    filtered = sorted(
        path.name for path in WORKFLOWS.glob("*.yml") if _pull_request_paths(path) is not None
    )
    assert filtered == sorted(LANES)


@pytest.mark.parametrize("workflow", sorted(LANES))
def test_a_lane_scope_covers_its_workflow_paths_filter(workflow: str) -> None:
    """Every pattern in the workflow's `paths:` must classify into one of its lane's
    scopes, or routing by the classifier would run that lane on fewer changes than today.
    `unknown` counts as covered: it requests the full gate, which runs every lane."""
    scopes = LANES[workflow]
    patterns = _pull_request_paths(WORKFLOWS / workflow)
    assert patterns, f"{workflow} has no pull_request paths filter"
    uncovered = []
    for pattern in patterns:
        # `**` becomes two path segments and `*` one character, which gives a concrete
        # path inside the pattern. Fail on any other glob form rather than check a
        # sample that does not represent it.
        assert not any(ch in pattern for ch in "?[!"), (
            f"{workflow}: {pattern!r} is a glob form this test does not expand"
        )
        sample = pattern.replace("**", "any/file").replace("*", "x")
        if not classifier.classify_path(sample) & (scopes | {"unknown"}):
            uncovered.append(pattern)
    assert not uncovered, (
        f"{workflow} runs on {uncovered}, but the classifier puts them in none of "
        f"{sorted(scopes)}. Add rules for them in scripts/classify_changes.py."
    )


# --- the command line


def test_json_output_lists_scopes_in_fixed_order(capsys: pytest.CaptureFixture[str]) -> None:
    assert classifier.main(["src/yazses/platform/macos/__init__.py", "docs/index.md"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "scopes": ["docs_design", "python_core", "macos"],
        "full": True,
    }


def test_paths_are_read_from_stdin_when_none_are_given(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("docs/index.md\r\nREADME.md\r\n"))
    assert classifier.main([]) == 0
    assert json.loads(capsys.readouterr().out) == {"scopes": ["docs_design", "unknown"], "full": True}


def test_github_output_has_one_boolean_per_scope_the_decision_and_the_list(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The output is appended to `$GITHUB_OUTPUT`, so it must end in a newline: without
    one, the next step's first line would be glued onto `scopes=`."""
    assert classifier.main(["--github-output", "docs/index.md"]) == 0
    out = capsys.readouterr().out
    assert out.endswith("\n")
    assert out.splitlines() == [
        "docs_design=true",
        "python_core=false",
        "tests=false",
        "android=false",
        "macos=false",
        "windows=false",
        "packaging=false",
        "workflow_security=false",
        "release=false",
        "unknown=false",
        "full=false",
        'scopes=["docs_design"]',
    ]


def test_the_script_run_as_a_command_agrees_with_the_import() -> None:
    """The issue's acceptance criterion: the same changed paths give the same answer
    locally and on a runner. Run as a subprocess and fed on stdin, the way a workflow
    step will run it, so this checks the command and not only the functions."""
    paths = [path for path, _ in AREAS + CROSS_CUTTING] + UNCLAIMED
    done = subprocess.run(
        [sys.executable, str(SCRIPT), "--github-output"],
        input="\n".join(paths) + "\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    assert done.stdout == classifier.github_output(classifier.classify(paths))
