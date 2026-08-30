"""The fuzz harnesses must keep working on every platform, not just the one that fuzzes.

`fuzz/` runs under Atheris, which publishes manylinux x86_64 wheels for CPython
3.12-3.14 and nothing else — no macOS, no Windows, no arm64 — so the fuzzing job is a
single scheduled Linux run. That leaves the harnesses in the position every piece of
scheduled tooling ends up in: they call into `postprocess/`, `commands/grammar.py`,
`config.py` and `tomlio.py`, those modules get refactored on a Tuesday, and nobody
finds out until the next Sunday cron — if anyone reads it.

So the harness bodies are exercised here, on every leg, without Atheris. `one_input`
is deliberately separate from the `test_one_input` entry point for exactly this reason:
it is the whole property under test and it needs nothing from libFuzzer.

The committed corpus is the input. That is not incidental either — a seed corpus is a
claim that these strings are worth mutating, and a seed the pipeline can no longer even
process is the one case a fuzzer cannot report, because libFuzzer treats a seed that
raises during the initial read as a crash before it has started searching.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

FUZZ = Path(__file__).resolve().parent.parent / "fuzz"
HARNESSES = ("fuzz_text_pipeline", "fuzz_config")


def _load(name: str):
    """Import a harness by path. `fuzz/` is not a package and not on `sys.path`."""
    spec = importlib.util.spec_from_file_location(f"_fuzz_{name}", FUZZ / f"{name}.py")
    assert spec and spec.loader, f"cannot load {name}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_harnesses_exist() -> None:
    """Named rather than globbed: the tests below iterate `HARNESSES`, and a renamed
    directory would leave them iterating nothing at all."""
    missing = [name for name in HARNESSES if not (FUZZ / f"{name}.py").exists()]
    assert not missing, f"missing harness: {missing}"


@pytest.mark.parametrize("name", HARNESSES)
def test_a_harness_imports_without_atheris(name: str) -> None:
    """Atheris is absent on most of this matrix. A harness that imports it at module
    scope would be uneditable and untestable anywhere but one Linux runner."""
    module = _load(name)
    assert callable(module.one_input)
    assert callable(module.test_one_input)


@pytest.mark.parametrize("name", HARNESSES)
def test_every_seed_in_the_corpus_survives_its_harness(name: str) -> None:
    """The seeds are realistic transcripts and realistic config files, and the property
    they carry is the one being fuzzed: nothing here may raise."""
    module = _load(name)
    seeds = sorted((FUZZ / "corpus" / name).glob("*"))
    assert seeds, f"no seed corpus for {name} -- the fuzzer would start from nothing"
    for seed in seeds:
        module.test_one_input(seed.read_bytes())


@pytest.mark.parametrize("name", HARNESSES)
def test_the_harness_reports_a_broken_pipeline_rather_than_swallowing_it(name: str) -> None:
    """Non-vacuity, and the property that makes the fuzzer worth running at all: an
    exception from the code under test must reach libFuzzer. A harness with a bare
    `except` around its body runs for a week and reports nothing, which reads exactly
    like a week with no bugs."""
    module = _load(name)
    source = (FUZZ / f"{name}.py").read_text(encoding="utf-8")
    assert "except Exception" not in source, (
        f"{name} swallows exceptions; libFuzzer would never see a crash"
    )
    assert "except BaseException" not in source

    # And prove it end to end rather than by reading: break one function the harness
    # calls and require the failure to propagate out of `test_one_input`.
    victim, sentinel = module._load(), RuntimeError("sentinel")
    key = "clean_text" if name == "fuzz_text_pipeline" else "load_config_checked"
    original = victim[key]

    def _boom(*args, **kwargs):
        raise sentinel

    victim[key] = _boom
    try:
        with pytest.raises(RuntimeError, match="sentinel"):
            module.test_one_input(b"hello")
    finally:
        victim[key] = original
