"""The ADR index must list the ADRs that exist.

`design/adr/README.md` listed **12 of 156**. It was written when there were eleven,
stayed right for one more, and then the corpus grew by an order of magnitude under it.
It was not dishonest — a footnote named the rest as `adr-v2-001..130` — but a range is
not an index, and that range had itself gone stale at 131.

This is the failure mode the repository keeps meeting from the other direction: a
document that was accurate when written and was never wired to the thing it describes.
The fix is the same one used for the feature-size table and the package manifests —
generate it, and fail the build when it drifts.

Only the region between the generator's markers is checked. The prose around it (why
the v1.0 series is binding, how to supersede one, why the mobile ADRs live in `docs/`)
is hand-written and must stay that way.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "gen-adr-index.py"
README = ROOT / "design" / "adr" / "README.md"
ADR_DIR = ROOT / "design" / "adr"


@pytest.fixture(scope="module")
def gen():
    """Load the generator as a module (its filename has a hyphen, so no import)."""
    spec = importlib.util.spec_from_file_location("gen_adr_index", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["gen_adr_index"] = module
    spec.loader.exec_module(module)
    return module


def test_there_are_adrs_to_index() -> None:
    """Guard the guard: an empty directory would make every check below vacuous —
    the exact shape this repo has now found three times in one week."""
    assert len(list(ADR_DIR.glob("adr-*.md"))) > 100


def test_the_index_lists_every_adr(gen) -> None:
    """The property, stated directly rather than via the generator's output, so a
    generator bug that dropped a series cannot make this pass."""
    body = README.read_text(encoding="utf-8")
    generated = body[body.index(gen.BEGIN) : body.index(gen.END)]
    missing = [
        path.name
        for path in sorted(ADR_DIR.glob("adr-*.md"))
        if f"({path.name})" not in generated
    ]
    assert not missing, (
        f"{len(missing)} ADRs are not in design/adr/README.md, starting with "
        f"{missing[:5]}. Run: python3 scripts/gen-adr-index.py"
    )


def test_the_index_lists_nothing_that_does_not_exist(gen) -> None:
    """The other direction: a deleted or renamed ADR leaves a dead link behind."""
    import re

    body = README.read_text(encoding="utf-8")
    generated = body[body.index(gen.BEGIN) : body.index(gen.END)]
    linked = set(re.findall(r"\]\((adr-[^)]+\.md)\)", generated))
    assert linked, "no ADR links parsed out of the generated block"
    dead = sorted(name for name in linked if not (ADR_DIR / name).is_file())
    assert not dead, f"the index links to files that do not exist: {dead}"


def test_running_the_generator_changes_nothing(gen) -> None:
    """Committed output must equal generated output. Run as a subprocess so this
    checks the script a contributor would actually run, not an import of it."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout


def test_the_handwritten_prose_survives_regeneration() -> None:
    """The generator owns one region and must not touch the rest. If it ever does,
    the reasoning about superseding ADRs and the mobile-series exception is gone —
    and it is the part nothing else records."""
    body = README.read_text(encoding="utf-8")
    for phrase in ("supersedes it", "docs/mobile/adr/"):
        assert phrase in body, (
            f"{phrase!r} has vanished from design/adr/README.md — the generator has "
            f"overrun the hand-written prose it is supposed to leave alone."
        )
