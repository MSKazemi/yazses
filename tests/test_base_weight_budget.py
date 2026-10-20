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
        "cmdsafety": "`Daemon.__init__` builds a `ConfirmGate()` unconditionally; the gate "
        "reads `[cmdsafety] enabled` per command. Pure, <1 ms.",
        "earcon": "`Daemon.__init__` builds `EarconPlayer(cfg.earcon.enabled)` "
        "unconditionally. Pure; the audio backend is imported on first play.",
        "facegesture": "reached through `yazses.config` -> `yazses.configcheck`, which derives "
        "the closed set for `[facegesture] gesture` from `facegesture.detector` rather than "
        "restating it. Pure, ~4 ms.",
        "learning": "`core/daemon.py` imports `build_writer` at module scope; it returns None "
        "when `[learning]` is off. The cryptography bindings are imported only when a corpus "
        "is opened.",
        "staged": "`Daemon.__init__` builds a `StagedBuffer()` unconditionally. Pure, ~1 ms.",
        "styleguard": "`Daemon.__init__` calls `build_style_rules(...)`, which returns no "
        "rules when `[styleguard]` is off. Pure, ~1 ms.",
        "tts": "`core/daemon.py` imports `build_tts`, which returns a null backend when "
        "`[tts]` is off; every engine is imported inside the factory.",
    },
    "help": {
        "facegesture": "`cli.main()` escapes `[section]` names via `cli_help`, which imports "
        "`yazses.config`; see the daemon entry for why that reaches `facegesture`.",
    },
}

#: Ceiling on ``yazses.*`` modules each probe may load. Recorded on Linux / CPython 3.14
#: on 2026-10-21 (daemon 92, help 32) with headroom for a module or two. Raising one is
#: allowed — say why in the PR; the number changing is the point of the diff.
MAX_YAZSES_MODULES: dict[str, int] = {"daemon": 96, "help": 35}

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
    ),
    "import yazses.cli": ("importlib.metadata",),
}


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


@pytest.mark.parametrize("probe", sorted(PROBES))
def test_the_yazses_module_count_stays_within_budget(
    probe: str, loaded: dict[str, list[str]]
) -> None:
    ours = [m for m in loaded[probe] if m == "yazses" or m.startswith("yazses.")]
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
