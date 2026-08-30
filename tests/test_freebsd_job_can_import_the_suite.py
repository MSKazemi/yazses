"""The FreeBSD leg must be able to *import* the suite it claims to run.

This job has failed twice for the same shape of reason, and neither was a defect in
the code it was meant to test:

* it used to run one file, so 48 of the suite's ~13,800 tests stood in for a
  platform claim -- widened, and the very first wide run found a shipped crash;
* it then installed `py${PYV}-yaml`, a port that FreeBSD's ports MOVED renamed to
  `py-pyyaml` on 2024-07-07. `pkg install` is all-or-nothing, so the stale name
  aborted `prepare` and the job ended before a single test ran, reporting a package
  rename as though FreeBSD itself were broken.

Both are invisible from every other leg: the dependency set is hand-written in one
workflow, for one OS, and nothing compares it to what the tests actually import. So
this compares them. A module-scope `import x` in a test file is not a skip when `x`
is absent -- it is a **collection error**, and thirteen of them at once is a red run
that says nothing about FreeBSD.

Both sides are derived. The import side is parsed out of `tests/`, discounting
anything a module-scope `pytest.importorskip` already guards; the install side is
parsed out of the job's own shell. The one hand-written part is the
package-name-to-module-name map below, which is checked against the workflow so it
cannot quietly describe packages the job stopped installing.
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys

import pytest
import yaml

WORKFLOW = pathlib.Path(__file__).resolve().parents[1] / ".github" / "workflows" / "test.yml"
TESTS = pathlib.Path(__file__).resolve().parent

# A distribution name is not an import name. Only entries whose package the job
# really installs are allowed (asserted below), so this cannot drift into fiction.
#
# `click` is here because it is not installed by name at all: typer depends on it,
# and `pip install typer` brings it. That is worth stating rather than leaving as a
# coincidence -- if typer ever vendors or drops it, the one test importing click at
# module scope becomes a collection error on this leg and nowhere else.
_PROVIDES = {
    "pyyaml": {"yaml"},
    "pillow": {"PIL"},
    "pytest-mock": {"pytest_mock"},
    "typer": {"typer", "click"},
}


def _freebsd_scripts() -> tuple[str, str]:
    """The job's `prepare` and `run` shell, straight out of the workflow."""
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    job = doc["jobs"]["freebsd"]
    for step in job["steps"]:
        with_ = step.get("with") or {}
        if "prepare" in with_ and "run" in with_:
            return with_["prepare"], with_["run"]
    raise AssertionError(
        "the freebsd job no longer has a step carrying both `prepare` and `run`. "
        "This test cannot report compliance about a job it cannot find."
    )


def _required_packages(prepare: str, run: str) -> set[str]:
    """Package names the job installs and *fails* without.

    The best-effort loop is deliberately excluded: those are allowed to be absent,
    so a module-scope import of one of them would still break collection.
    """
    packages: set[str] = set()

    # `pkg install -y "py${PYV}-numpy" ...` -- but only the unconditional ones. The
    # optional loop is a `for opt in ...; do pkg install -y "$opt" || echo`, so it is
    # skipped by taking only lines that name packages literally.
    for line in prepare.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "||" in stripped or stripped.startswith("for "):
            continue
        for name in re.findall(r'py\$\{PYV\}-([A-Za-z0-9_.-]+)', stripped):
            packages.add(name.lower())

    # `python -m pip install a b c`, ignoring flags and the editable install of the
    # project itself.
    for line in run.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "pip install" not in stripped:
            continue
        for token in stripped.split("pip install", 1)[1].split():
            if token.startswith("-") or token == "." or "/" in token:
                continue
            packages.add(re.split(r"[<>=!\[]", token)[0].lower())

    return packages


def _available_modules() -> set[str]:
    prepare, run = _freebsd_scripts()
    packages = _required_packages(prepare, run)
    assert len(packages) >= 5, (
        f"only {sorted(packages)} were parsed out of the freebsd job's shell. A parse "
        "that finds almost nothing must fail rather than report that every import is "
        "satisfied."
    )
    modules = set()
    for package in packages:
        modules |= _PROVIDES.get(package, {package.replace("-", "_")})
    return modules


def _module_scope_imports() -> dict[str, list[str]]:
    """Third-party modules imported at module scope, and where.

    `pytest.importorskip("x")` anywhere in the file exempts `x`: at module scope it
    skips the whole module before the import line is reached, which is the pattern
    PySide6, Pillow and evdev already use here.
    """
    imports: dict[str, list[str]] = {}
    for path in sorted(TESTS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        guarded = {
            node.args[0].value.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "importorskip"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        }
        for node in tree.body:  # module scope only -- a nested import is not fatal
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module.split(".")[0]]
            else:
                continue
            for name in names:
                if name in sys.stdlib_module_names or name == "yazses" or name in guarded:
                    continue
                if name == "tests" or (TESTS / f"{name}.py").exists():
                    continue  # a sibling test module, not a dependency
                imports.setdefault(name, []).append(path.name)
    return imports


def test_the_probe_finds_the_job_and_its_packages() -> None:
    """Non-vacuity for the install side. Every assertion below is satisfied by an
    empty parse, so the parse is what gets checked first."""
    prepare, run = _freebsd_scripts()
    packages = _required_packages(prepare, run)
    assert "numpy" in packages, f"the pkg parse missed numpy: {sorted(packages)}"
    assert "pytest" in packages, f"the pip parse missed pytest: {sorted(packages)}"
    assert "pillow" not in packages, (
        "pillow is installed in the best-effort loop and may legitimately be absent, "
        "so it must not count as available to a module-scope import."
    )


def test_the_import_probe_finds_the_suites_real_dependencies() -> None:
    """Non-vacuity for the import side."""
    imports = _module_scope_imports()
    assert "pytest" in imports and "numpy" in imports, sorted(imports)
    assert "PySide6" not in imports, (
        "PySide6 is guarded by `pytest.importorskip` in every file that imports it; "
        "seeing it here means the guard-detection stopped working."
    )


@pytest.mark.parametrize("module", sorted(_module_scope_imports()))
def test_every_module_scope_import_is_installed_on_freebsd(module: str) -> None:
    available = _available_modules()
    assert module in available, (
        f"{module} is imported at module scope by "
        f"{', '.join(_module_scope_imports()[module])} but the freebsd job does not "
        f"install anything providing it. On that leg this is a collection error, not "
        f"a skip, and it fails the whole run before any FreeBSD-specific test executes. "
        f"Add it to the job's `pip install` line, or guard the import with "
        f"`pytest.importorskip`. Available there: {sorted(available)}"
    )


def test_the_provides_map_describes_packages_the_job_installs() -> None:
    """A translation table for packages nobody installs any more is how a guard
    starts describing a world that has moved on."""
    prepare, run = _freebsd_scripts()
    installed = _required_packages(prepare, run)
    # pillow is in the best-effort loop rather than the required set, and typer pulls
    # click in transitively; both are named in the map for a reason, so the check is
    # that the *package* appears in the job's shell at all.
    shell = prepare + run
    for package in _PROVIDES:
        assert package in installed or package in shell, (
            f"_PROVIDES maps {package!r}, which the freebsd job no longer mentions."
        )


def test_the_freebsd_job_runs_the_whole_suite() -> None:
    """It ran one file once, and 48 tests read as platform coverage for weeks."""
    _, run = _freebsd_scripts()
    assert re.search(r"pytest\s+tests/(\s|$)", run), (
        "the freebsd job no longer runs `pytest tests/`. Narrowing it to specific "
        "files is what made 48 tests stand in for the whole suite; if that is "
        "intended, this test is the place to say why."
    )
