"""A WER measured on the hard split may not be published under the clean one's name.

`docs/benchmarks.md` has always carried the sentence "your dictation WER will be worse
than this" about LibriSpeech `test-clean`, and until now the harness could not measure
anything worse -- the split was a module constant. Making it a parameter creates one new
way to be wrong: a `test-other` run writing `paper/results/wer.json`, which is the file
`tests/test_benchmarks_match_results.py` checks the headline table against. The page
would then be "verified" against numbers from a corpus it does not name.

So the split travels with the call, lands in the result's `config` block, and decides
the result file's name.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parent.parent / "paper" / "benchmark"


def _load(name: str):
    """Import a bench module by path -- `paper/` is not a package."""
    sys.path.insert(0, str(BENCH))
    try:
        spec = importlib.util.spec_from_file_location(name, BENCH / f"{name}.py")
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(BENCH))


def _refuse_to_load(*_args, **_kwargs):
    """Stand in for the engine factory: no model is downloaded in a unit test.

    `run()` records a load failure and carries on, which is exactly the path that
    leaves `config` populated and `models` empty -- all this test needs.
    """
    raise RuntimeError("no model on this machine")


def test_the_two_splits_resolve_to_different_directories() -> None:
    common = _load("_common")
    clean = common.librispeech_dir("test-clean")
    other = common.librispeech_dir("test-other")
    assert clean != other
    assert clean.name == "test-clean" and other.name == "test-other"
    assert clean.parent == other.parent


def test_an_unknown_split_is_refused_by_name() -> None:
    """A typo must not fall through to an empty corpus and a WER of zero."""
    common = _load("_common")
    with pytest.raises(ValueError, match="test-clean"):
        common.librispeech_dir("test-clea")


def test_the_subset_refuses_an_unknown_split_before_touching_the_disk() -> None:
    common = _load("_common")
    with pytest.raises(ValueError):
        common.librispeech_subset(5, split="dev-clean")


def test_the_split_reaches_the_result_config(monkeypatch) -> None:
    """A number is never quotable without the corpus it was measured on."""
    bench_wer = _load("bench_wer")
    rows = [("1-1-0000", Path("/nonexistent.flac"), "hello world", 1.0)]
    monkeypatch.setattr(
        bench_wer,
        "librispeech_subset",
        lambda _n, stratified=True, split="test-clean": rows,
    )
    monkeypatch.setattr(bench_wer, "_engine_versions", lambda specs: {})
    monkeypatch.setattr(bench_wer, "_build", _refuse_to_load)

    out = bench_wer.run(1, [("tiny.en", "faster-whisper", "tiny.en")], 0, "test-other")
    cfg = out["config"]
    assert cfg["dataset"] == "LibriSpeech test-other"
    assert "test-other.tar.gz" in cfg["dataset_source"]
    assert "test-other" in cfg["selection"]


def test_the_default_split_is_still_test_clean(monkeypatch) -> None:
    bench_wer = _load("bench_wer")
    rows = [("1-1-0000", Path("/nonexistent.flac"), "hello world", 1.0)]
    monkeypatch.setattr(
        bench_wer,
        "librispeech_subset",
        lambda _n, stratified=True, split="test-clean": rows,
    )
    monkeypatch.setattr(bench_wer, "_engine_versions", lambda specs: {})
    monkeypatch.setattr(bench_wer, "_build", _refuse_to_load)

    cfg = bench_wer.run(1, [("tiny.en", "faster-whisper", "tiny.en")])["config"]
    assert cfg["dataset"] == "LibriSpeech test-clean"


def test_a_hard_split_run_does_not_write_the_headline_result_file() -> None:
    """The `__main__` block picks the result name from the split.

    Asserted on the source rather than by running it: the entry point writes into
    `paper/results/`, and a test that executes it would either need a real corpus or
    would overwrite the very file it is protecting.
    """
    source = (BENCH / "bench_wer.py").read_text(encoding="utf-8")
    assert 'name = "wer" if split == "test-clean" else f"wer-{split}"' in source
    assert 'write_result(name,' in source
