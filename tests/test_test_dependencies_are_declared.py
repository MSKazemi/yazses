"""Everything `tests/` imports must be named in `pyproject.toml`.

Thirteen test files `import yaml` at module scope and one imports `click`, and
neither was declared anywhere in this project. They arrived as transitive
dependencies -- yaml from mkdocs, click from typer and huggingface-hub -- so the
suite's ability to *collect at all* rested on the dependency lists of a docs tool
and a CLI framework, neither of which has any reason to keep them.

That is not a hypothetical. typer dropped its click dependency at 0.27.2, and the
FreeBSD leg -- the one environment that installs test dependencies by name rather
than from this file -- stopped at `ModuleNotFoundError: No module named 'click'`
before any test ran. On every other leg it stayed invisible, because something else
in a 279-package lockfile still happened to pull it in.

An undeclared import is not a missing feature; it is a dependency the project has
without saying so, and it fails all at once, everywhere, on someone else's release.
So: the imports are parsed out of `tests/`, the declarations out of `pyproject.toml`,
and the module-to-distribution mapping comes from the installed metadata rather than
from a table anybody has to maintain.
"""

from __future__ import annotations

import pathlib
import tomllib
from importlib.metadata import packages_distributions

import pytest

from tests.test_freebsd_job_can_import_the_suite import _module_scope_imports

PYPROJECT = pathlib.Path(__file__).resolve().parents[1] / "pyproject.toml"


def _normalise(name: str) -> str:
    """PEP 503: distribution names compare case-insensitively with -_. folded."""
    out = []
    for ch in name.lower():
        out.append("-" if ch in "-_." else ch)
    return "".join(out)


def _requirement_name(spec: str) -> str:
    """The distribution out of a requirement string, extras and markers dropped."""
    head = spec.split(";", 1)[0].strip()
    for stop in ("[", "<", ">", "=", "!", "~", "@", " "):
        head = head.split(stop, 1)[0]
    return _normalise(head.strip())


def _declared() -> set[str]:
    """Every distribution this project declares, wherever it declares it."""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    specs: list[str] = list(data.get("project", {}).get("dependencies", []))
    for group in data.get("project", {}).get("optional-dependencies", {}).values():
        specs += group
    for group in data.get("dependency-groups", {}).values():
        # A PEP 735 group may include another group as `{include-group = "dev"}`.
        specs += [item for item in group if isinstance(item, str)]
    names = {_requirement_name(s) for s in specs}
    names.discard("")
    assert len(names) >= 20, (
        f"only {len(names)} declared distributions were parsed out of pyproject.toml. "
        "A parse that finds almost nothing must fail rather than report that every "
        "import is declared."
    )
    return names


def _distributions_for(module: str) -> set[str]:
    """Which installed distributions provide *module*, per its own metadata.

    Derived rather than tabulated: `pyyaml` provides `yaml` and `pytest-mock`
    provides `pytest_mock`, and a hand-written map of those is one more thing to
    remember when a dependency is renamed.
    """
    return {_normalise(d) for d in packages_distributions().get(module, [])}


def test_the_probes_are_not_empty() -> None:
    """Both sides first: every assertion below passes on an empty parse."""
    declared = _declared()
    assert "pytest" in declared and "typer" in declared, sorted(declared)[:20]
    imports = _module_scope_imports()
    assert "yaml" in imports and "numpy" in imports, sorted(imports)
    assert _distributions_for("yaml") == {"pyyaml"}, (
        "importlib.metadata could not resolve `yaml` to PyYAML, so this guard cannot "
        "tell a declared dependency from an undeclared one."
    )


@pytest.mark.parametrize("module", sorted(_module_scope_imports()))
def test_every_module_scope_test_import_is_declared(module: str) -> None:
    declared = _declared()
    providers = _distributions_for(module)
    assert providers, (
        f"`{module}` is imported at module scope by "
        f"{', '.join(_module_scope_imports()[module])} but no installed distribution "
        f"claims to provide it, so it cannot be checked against pyproject.toml."
    )
    assert providers & declared, (
        f"`{module}` is imported at module scope by "
        f"{', '.join(_module_scope_imports()[module])} and pyproject.toml declares "
        f"none of {sorted(providers)}. It is reaching the suite as somebody else's "
        f"transitive dependency, which means a release of that package can turn this "
        f"whole suite red -- as a collection error, on every platform at once. Add it "
        f"to the `dev` dependency group, or guard the import with "
        f"`pytest.importorskip`."
    )
