"""A feature that is off by default costs a default start nothing — measured, not hoped.

YazSes has ~150 feature packages under ``src/yazses/`` and every one ships with
``enabled = false`` (AGENTS.md rule 2). That rule says what a user *sees* on a fresh
install; it says nothing about what they *pay*. A feature whose package is imported at
module scope by the daemon or the CLI is loaded — and its own imports with it — on every
start, by every user, whether or not they ever turn it on. Nothing fails; startup just
gets a little slower with each feature, which is the regression a functional test never
sees.

This file is the budget, in three parts:

1. **No disabled-by-default feature package is imported** by ``import yazses.main`` (the
   ``yazses-daemon`` entry point, which imports ``yazses.core.daemon``) or by
   ``yazses --help`` (``cli.main()`` end to end). The set of such packages is
   **derived** — every ``[section]`` of :class:`yazses.config.Config` whose default has
   ``enabled = False`` and whose name is a package under ``src/yazses/`` — so a feature
   added tomorrow is covered without anybody remembering to list it.
2. **A ratchet, not an amnesty.** The packages that are imported today, each with the
   reason, live in :data:`KNOWN_EAGER`. A new one fails; one that stops being imported
   also fails, until it is deleted from the list — so the list can only shrink.
3. **A module-count ceiling** on the ``yazses.*`` modules each path loads, so a core
   module growing a new eager import is visible as a number in review.

Counts and names, never wall-clock: ``sys.modules`` after a fresh interpreter's import is
exact and reproducible on a busy CI runner, a timing is not. The timing budget lives in
``scripts/check_dependency_budget.py`` (CI-enforced with a 1.5x tolerance, advisory on a
laptop). How a contributor stays inside all of this: ``docs/contribute/startup-budget.md``.

``tests/test_default_start_stays_light.py`` is the older, hand-listed sibling of part 1
(it also covers packages that have no config section of their own, such as
``perception`` and ``settingsui``); this file is the derived, ratcheted version.
"""
from __future__ import annotations

import ast
import dataclasses
import json
import subprocess
import sys
from pathlib import Path

import pytest

import yazses
from yazses.config import Config

PACKAGE_ROOT = Path(yazses.__file__).resolve().parent

#: Disabled-by-default feature packages that a start imports today, and why. Each entry is
#: a debt with a reason, not a permission: the test fails when an entry stops being true,
#: so whoever makes one lazy must delete its line. Keyed by probe, then package.
KNOWN_EAGER: dict[str, dict[str, str]] = {
    "daemon": {
        # Both kept on purpose on 2026-10-21, when earcon, facegesture, learning,
        # styleguard and tts were made lazy. Neither is an import move: each would need
        # the daemon to answer for an object it no longer holds.
        "cmdsafety": "`Daemon._cmdsafety` is one held-command slot shared by four "
        "consumers -- `[cmdsafety]`, `[checkdigit]`, `[reask]` and the face switch's "
        "confirm/cancel -- reached from the dictation and camera threads. Building it "
        "lazily needs a locked accessor, or a first use from two threads could hold a "
        "command in a gate nobody reads. Pure, 2 modules, <1 ms.",
        "staged": "`_handle_status` reports `staged_state()` on every IPC status poll "
        "(the tray and overlay poll several times a second), so a lazy import would load "
        "on the first poll anyway. Pure, 2 modules, ~1 ms.",
    },
    "help": {},
}

def os_backend_packages() -> frozenset[str]:
    """The packages where an OS difference is *supposed* to live (AGENTS.md rule 6).

    Derived from where ``platform/factory.py`` imports ``build_platform`` -- the
    registration of an OS: ``yazses.platform.linux``, ``.macos``, ``.windows``,
    ``.bsd`` -- rather than listed, so a new OS backend is excluded the day it is
    registered. Their modules are not counted against a ceiling: how many modules a
    backend needs is a property of the OS, not of a change in review.
    """
    tree = ast.parse((PACKAGE_ROOT / "platform" / "factory.py").read_text(encoding="utf-8"))
    out = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and (node.module or "").startswith("yazses.platform.")
            and any(alias.name == "build_platform" for alias in node.names)
        ):
            out.add(".".join(node.module.split(".")[:3]))
    return frozenset(out)

#: Ceiling on ``yazses.*`` modules each probe may load, excluding `os_backend_packages()`.
#:
#: Recorded on Linux / CPython 3.14 on 2026-10-21: daemon **73**, help **25**. The
#: count does not depend on the OS by construction -- no module either probe loads
#: imports a ``yazses`` module under a module-scope platform or version branch, which
#: :func:`test_the_module_count_cannot_depend_on_the_os` asserts -- so the same ceiling
#: is right on the Windows and macOS legs. The **+3 headroom** covers what that AST
#: check cannot see (an import made by a function a module calls at import time on one
#: OS only); it is a review signal, not an allowance. Raising one is allowed -- say why
#: in the PR; the number changing is the point of the diff.
MAX_YAZSES_MODULES: dict[str, int] = {"daemon": 76, "help": 28}

_HELP_PROBE = """
import contextlib, io, sys
sys.argv = ["yazses", "--help"]
from yazses.cli import main
with contextlib.redirect_stdout(io.StringIO()) as out:
    try:
        main()
    except SystemExit:
        pass
assert "Usage" in out.getvalue(), "the --help probe rendered no help"
"""

_VERSION_PROBE = """
import contextlib, io, sys
sys.argv = ["yazses", "--version"]
from yazses.cli import main
with contextlib.redirect_stdout(io.StringIO()) as out:
    try:
        main()
    except SystemExit:
        pass
assert out.getvalue().strip(), "the --version probe printed nothing"
"""

PROBES: dict[str, str] = {
    "daemon": "import yazses.main",
    "help": _HELP_PROBE,
}
PROBE_LABELS: dict[str, str] = {"daemon": "import yazses.main", "help": "yazses --help"}

#: Standard-library and base-dependency modules that only an opt-in path needs, each made
#: lazy on 2026-10-21 and measured then: the network stack (~13 ms, LLM cleanup's Ollama
#: backend), asyncio (~11 ms, remote mode), the cryptography bindings (~7 ms, the learning
#: corpus) and importlib.metadata (only `--version` reads it). Keyed by the statement.
NOT_LOADED_BY: dict[str, tuple[str, ...]] = {
    "import yazses.main": (
        "asyncio",
        "urllib.request",
        "http.client",
        "ssl",
        "cryptography",
        "importlib.metadata",
        # The learning corpus's store; reached at start only while `core/daemon.py`
        # imported `learning.capture` at module scope (made lazy 2026-10-21).
        "sqlite3",
    ),
    "import yazses.cli": ("importlib.metadata",),
}

#: `cli.main()` runs on every CLI invocation. It imported the whole of `yazses.config`
#: (~66 ms measured, the largest module in the tree) only to escape `[section]` names in
#: help text, until 2026-10-21; `cli_help` now reads the generated
#: `yazses.config_sections` instead. A command that needs the config imports it itself.
CLI_ENTRY_PROBES: dict[str, str] = {"yazses --version": _VERSION_PROBE, "yazses --help": _HELP_PROBE}


def disabled_by_default_packages() -> frozenset[str]:
    """Every feature package whose config section defaults to ``enabled = False``."""
    cfg = Config()
    out = set()
    for field in dataclasses.fields(cfg):
        section = getattr(cfg, field.name)
        if not dataclasses.is_dataclass(section):
            continue
        if getattr(section, "enabled", None) is not False:
            continue
        if (PACKAGE_ROOT / field.name / "__init__.py").is_file():
            out.add(field.name)
    return frozenset(out)


def _loaded(statement: str) -> list[str]:
    """``sys.modules`` of a fresh interpreter after *statement*.

    A subprocess is the only honest way to ask: this pytest session has already imported
    half the codebase, so an in-process check would pass or fail on collection order.
    """
    code = statement + "\nimport json, sys\nprint(json.dumps(sorted(sys.modules)))\n"
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def eager_feature_packages(loaded: list[str], disabled: frozenset[str]) -> set[str]:
    """The disabled-by-default packages that have at least one module in *loaded*."""
    found = set()
    for name in loaded:
        parts = name.split(".")
        if len(parts) >= 2 and parts[0] == "yazses" and parts[1] in disabled:
            found.add(parts[1])
    return found


@pytest.fixture(scope="module")
def loaded() -> dict[str, list[str]]:
    return {probe: _loaded(stmt) for probe, stmt in PROBES.items()}


def test_the_derived_feature_set_is_not_empty() -> None:
    """A derivation that silently found nothing would make every check below green."""
    disabled = disabled_by_default_packages()
    assert len(disabled) >= 50, sorted(disabled)
    # Spot-check both directions: an opt-in feature is in, the core is out.
    assert {"gaze", "meeting", "tts", "learning"} <= disabled
    assert not {"core", "config", "stt", "audio", "commands"} & disabled


def test_the_probes_see_the_entry_points(loaded: dict[str, list[str]]) -> None:
    assert "yazses.core.daemon" in loaded["daemon"]
    assert "yazses.cli" in loaded["help"]


@pytest.mark.parametrize("probe", sorted(PROBES))
def test_no_new_disabled_feature_is_imported_at_start(
    probe: str, loaded: dict[str, list[str]]
) -> None:
    eager = eager_feature_packages(loaded[probe], disabled_by_default_packages())
    new = sorted(eager - set(KNOWN_EAGER[probe]))
    assert not new, (
        f"`{PROBE_LABELS[probe]}` now imports disabled-by-default feature "
        f"package(s) {new}. A user who never enables them pays for them on every start. "
        "Import the feature inside the function that runs when it is enabled (or under "
        "`if TYPE_CHECKING:` if it is only a type) -- see docs/contribute/startup-budget.md. "
        "Find the importer with `uv run python -X importtime -c 'import yazses.main' "
        "2>&1 | grep -B5 yazses.<package>`."
    )


@pytest.mark.parametrize("probe", sorted(PROBES))
def test_the_known_eager_list_only_shrinks(probe: str, loaded: dict[str, list[str]]) -> None:
    disabled = disabled_by_default_packages()
    listed = set(KNOWN_EAGER[probe])
    not_features = sorted(listed - disabled)
    assert not not_features, (
        f"KNOWN_EAGER[{probe!r}] lists {not_features}, which are not disabled-by-default "
        "feature packages -- the entry excuses nothing; delete it."
    )
    stale = sorted(listed - eager_feature_packages(loaded[probe], disabled))
    assert not stale, (
        f"{stale} are no longer imported by the {probe} probe -- well done. Delete them "
        f"from KNOWN_EAGER[{probe!r}] so they cannot quietly come back."
    )


def counted_yazses_modules(loaded: list[str]) -> list[str]:
    """The ``yazses.*`` modules a ceiling counts: everything but ``platform/<os>/``."""
    backends = os_backend_packages()
    return [
        m
        for m in loaded
        if (m == "yazses" or m.startswith("yazses."))
        and not any(m == b or m.startswith(b + ".") for b in backends)
    ]


@pytest.mark.parametrize("probe", sorted(PROBES))
def test_the_yazses_module_count_stays_within_budget(
    probe: str, loaded: dict[str, list[str]]
) -> None:
    ours = counted_yazses_modules(loaded[probe])
    ceiling = MAX_YAZSES_MODULES[probe]
    assert len(ours) <= ceiling, (
        f"the {probe} probe loads {len(ours)} yazses modules, over its budget of {ceiling}. "
        "Something at module scope gained an import. If it is deliberate, raise "
        "MAX_YAZSES_MODULES in this file and say why in the PR.\n" + "\n".join(ours)
    )


@pytest.mark.parametrize(
    ("statement", "module"),
    [(s, m) for s, mods in NOT_LOADED_BY.items() for m in mods],
)
def test_an_opt_in_dependency_stays_out_of_a_default_start(statement: str, module: str) -> None:
    loaded = _loaded(statement)
    assert any(m.startswith("yazses.") for m in loaded), "the probe imported nothing"
    leaked = [m for m in loaded if m == module or m.startswith(module + ".")]
    assert not leaked, (
        f"`{statement}` loads {module} again. It was made lazy because only an opt-in "
        "path uses it; find the module-scope import with `python -X importtime` and move "
        "it into the function that needs it."
    )


def test_the_guard_fires_on_a_real_eager_import() -> None:
    """Prove the check, not just the tree: an injected eager import must be reported.

    ``wordgoal`` is a small, dependency-free, disabled-by-default package; importing it
    beside the daemon is exactly the shape of the regression this file exists for.
    """
    disabled = disabled_by_default_packages()
    assert "wordgoal" in disabled
    loaded = _loaded("import yazses.main\nimport yazses.wordgoal")
    eager = eager_feature_packages(loaded, disabled)
    assert "wordgoal" in eager - set(KNOWN_EAGER["daemon"])


def test_the_matcher_reads_package_boundaries() -> None:
    disabled = frozenset({"tts", "gaze"})
    loaded = ["yazses.tts.factory", "yazses.ttsx", "yazses.core.gaze", "yazses", "gaze"]
    assert eager_feature_packages(loaded, disabled) == {"tts"}


# --- the CLI entry point ---------------------------------------------------------------


@pytest.mark.parametrize("label", sorted(CLI_ENTRY_PROBES))
def test_the_cli_entry_point_does_not_import_the_config(label: str) -> None:
    loaded = _loaded(CLI_ENTRY_PROBES[label])
    assert "yazses.cli" in loaded, "the probe did not reach the CLI"
    assert "yazses.config" not in loaded, (
        f"`{label}` imports yazses.config again (~66 ms on every invocation, measured). "
        "`cli.main()` must not need it: `cli_help` escapes `[section]` names from the "
        "generated `yazses.config_sections`. Find the importer with "
        f"`python -X importtime` on the probe in {Path(__file__).name}."
    )


# --- the ceiling must mean the same thing on every OS -----------------------------------

#: Spellings of "which OS / which interpreter is this" a module-scope branch tests.
_OS_TESTS = (
    "sys.platform", "os.name", "platform.system", "platform.machine", "version_info",
    "IS_WINDOWS", "IS_MACOS", "IS_MAC", "IS_LINUX", "WINDOWS", "MACOS",
)


def platform_branch_imports(source: str) -> list[str]:
    """``yazses`` imports made under a module-scope OS or version branch in *source*.

    Such an import would make a probe's module count depend on the runner, so a
    ceiling measured on Linux could fail on Windows or macOS for no change at all.
    """
    found = []
    for node in ast.parse(source).body:
        if not isinstance(node, ast.If):
            continue
        test = ast.unparse(node.test)
        if not any(key in test for key in _OS_TESTS):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.ImportFrom) and (inner.module or "").startswith("yazses"):
                found.append(f"if {test}: from {inner.module} import ...")
            elif isinstance(inner, ast.Import):
                found += [f"if {test}: import {a.name}" for a in inner.names
                          if a.name.startswith("yazses")]
    return found


@pytest.mark.parametrize("probe", sorted(PROBES))
def test_the_module_count_cannot_depend_on_the_os(
    probe: str, loaded: dict[str, list[str]]
) -> None:
    """Why one Linux-measured ceiling is valid on the Windows and macOS legs too.

    `platform/<os>/` is excluded from the count (`os_backend_packages`). Everything
    else a probe loads must import the same ``yazses`` modules on every OS, which holds
    as long as none of them imports one under a module-scope platform branch.
    """
    offenders = {}
    for name in counted_yazses_modules(loaded[probe]):
        rel = Path(*name.split(".")[1:])
        path = PACKAGE_ROOT / rel / "__init__.py"
        if not path.is_file():
            path = (PACKAGE_ROOT / rel).with_suffix(".py")
        if not path.is_file():  # `yazses` itself
            path = PACKAGE_ROOT / "__init__.py"
        hits = platform_branch_imports(path.read_text(encoding="utf-8"))
        if hits:
            offenders[name] = hits
    assert not offenders, (
        f"the {probe} probe loads modules that import yazses modules under an OS branch, "
        "so its module count differs per OS and MAX_YAZSES_MODULES (measured on Linux) "
        f"can fail on another runner: {offenders}. Move the OS-specific import behind "
        "`platform/<os>/` or into the function that needs it."
    )


def test_the_os_branch_scanner_sees_a_platform_import() -> None:
    """Red-green for the scanner: an empty answer must mean "none", not "cannot see"."""
    src = (
        "import sys\n"
        "if sys.platform == 'win32':\n"
        "    from yazses.platform.windows import keys\n"
        "else:\n"
        "    import yazses.platform.linux.keys\n"
        "if TYPE_CHECKING:\n"
        "    from yazses.config import Config\n"
    )
    assert platform_branch_imports(src) == [
        "if sys.platform == 'win32': from yazses.platform.windows import ...",
        "if sys.platform == 'win32': import yazses.platform.linux.keys",
    ]
    assert platform_branch_imports("import os\nif os.name == 'nt':\n    import ctypes\n") == []


def test_the_os_backends_are_derived_from_the_factory() -> None:
    backends = os_backend_packages()
    assert {"yazses.platform.linux", "yazses.platform.macos",
            "yazses.platform.windows"} <= backends
    assert "yazses.platform.base" not in backends
    counted = counted_yazses_modules(
        ["yazses", "yazses.platform", "yazses.platform.linux", "yazses.platform.linux.tray",
         "yazses.platform.base", "yazses.platform.linuxish"]
    )
    assert counted == ["yazses", "yazses.platform", "yazses.platform.base",
                       "yazses.platform.linuxish"]
