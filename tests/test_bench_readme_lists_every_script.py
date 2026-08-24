"""`paper/benchmark/README.md` must name every script in that directory.

A hand-maintained table of what a directory contains is only ever as complete as the
day it was written, and this one had fallen five scripts behind: `bench_beam.py`,
`bench_onset.py`, `bench_plausibility.py`, `bench_streaming.py` and
`bench_throughput.py` were all being run and quoted while the README said the harness
measured WER, latency, commands, VAD, diarization and meta. A reader deciding whether
a published figure was reproducible would have concluded the instrument did not exist.

The set is derived from the directory rather than restated, so a script added tomorrow
fails this test on the day it lands instead of drifting out of the documentation
silently. That is the same reason `benchmark_deps.py` derives its skip list from
`pyproject.toml` instead of keeping one.
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "paper" / "benchmark"
README = BENCH / "README.md"

#: A support module, not an experiment: imported by the scripts rather than run, so a
#: row in a table of "what each script measures" would be misleading. `make_corpus.py`
#: is deliberately *not* here -- it is run from the command line and is documented in
#: prose rather than in the table, which the name check accepts either way.
NOT_AN_EXPERIMENT = {"_common.py"}


def _scripts() -> list[str]:
    return sorted(
        p.name for p in BENCH.glob("*.py")
        if not p.name.startswith("__") and p.name not in NOT_AN_EXPERIMENT
    )


def test_the_harness_and_its_readme_both_exist() -> None:
    """Guard the guard: an empty directory or a missing README makes the
    parametrized check below collect nothing and pass."""
    assert README.is_file()
    assert len(_scripts()) >= 8, f"only found {_scripts()}"


@pytest.mark.parametrize("script", _scripts())
def test_every_script_is_named_in_the_readme(script: str) -> None:
    text = README.read_text(encoding="utf-8")
    assert f"`{script}`" in text, (
        f"{script} is in paper/benchmark/ and paper/benchmark/README.md never names "
        "it. Add a row to the table saying what it measures and what shipping code it "
        "reuses -- an undocumented instrument reads as an instrument that does not "
        "exist, which is how five of these went unpublished."
    )


def test_the_readme_does_not_name_a_script_that_is_gone() -> None:
    """The other direction. A row for a deleted script reads as a live capability."""
    import re

    text = README.read_text(encoding="utf-8")
    named = set(re.findall(r"`((?:bench|analyze|run|make)_[a-z_]+\.py)`", text))
    missing = sorted(named - set(_scripts()))
    assert not missing, f"README names scripts that are not in paper/benchmark/: {missing}"
