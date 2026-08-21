"""What `yazses <anything>` pays before it does anything (ADR-016, ADR-018).

Every CLI invocation imports `yazses.cli` — `status`, `stop`, `--help`, and the
shell completion that runs on each Tab. So an import at module scope in that file
is a tax on all of them, paid by users who will never call the command that needs
it.

Two were measured at 42% of a 181 ms cold start: `yazses.system.updater` pulled in
`urllib.request` and `http.client` (21 ms) for a network stack only `yazses update`
uses, and `yazses/__init__` resolved the installed version eagerly through
`importlib.metadata` (52 ms) for a string most commands never read.

These are guards, not benchmarks: a wall-clock assertion would be flaky on a busy
CI runner, while "did this module get imported" is exact and reproducible. Each
name here was verified absent from the import graph before being listed — nothing
is asserted that was not first observed.
"""
from __future__ import annotations

import subprocess
import sys

import pytest

# Imported for `yazses update` alone; the network stack has no business being
# resolved by `yazses status`.
NETWORK = ("urllib.request", "http.client")


def _modules_after(statement: str) -> set[str]:
    """`sys.modules` in a fresh interpreter that ran *statement*.

    A subprocess is the only honest way to ask: this test session has already
    imported half the codebase, so an in-process check would pass or fail on the
    order pytest happened to collect in.
    """
    proc = subprocess.run(
        [sys.executable, "-c", f"{statement}\nimport sys\nprint('\\n'.join(sys.modules))"],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    return set(proc.stdout.split())


@pytest.mark.parametrize("module", NETWORK)
def test_importing_the_cli_does_not_build_a_network_stack(module: str) -> None:
    assert module not in _modules_after("import yazses.cli"), (
        f"`import yazses.cli` pulls in {module}. Something at module scope reached "
        f"for the network layer — `yazses.system.updater` is the usual culprit. "
        f"Import it inside the command that needs it."
    )


def test_the_package_does_not_resolve_its_version_until_asked() -> None:
    """`import yazses` is the cheapest thing the CLI does; keep it that way.

    `importlib.metadata` walks `sys.path` looking for a `.dist-info`, which is the
    single most expensive import in the tree. `__version__` stays lazy (PEP 562
    module `__getattr__`) so only the commands that print it pay for it.
    """
    assert "importlib.metadata" not in _modules_after("import yazses")


def test_the_version_is_still_correct_when_it_is_read() -> None:
    """Laziness must not change the answer — the reason it reads metadata at all
    is that a hardcoded constant drifted (it said 2.10.0.dev5 at 2.12.1)."""
    import importlib.metadata

    import yazses

    assert yazses.__version__ == importlib.metadata.version("yazses")


def test_dir_and_all_still_advertise_the_version() -> None:
    """A module `__getattr__` is invisible to `dir()` unless `__dir__` says so, and
    `from yazses import *` follows `__all__`. Both must keep working."""
    import yazses

    assert "__version__" in yazses.__all__
    assert "__version__" in dir(yazses)
