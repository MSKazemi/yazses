"""The provenance block must name everything that changes the number.

The block exists so a benchmark figure is never quoted without the conditions it was
measured under. It listed the model, the CPU and the Python/numpy/faster-whisper
versions -- and not the three things that were actually observed to move a WER:

* **CTranslate2**, which owns the int8 kernels; faster-whisper only wraps it, so its
  version was the one absent from a block that recorded the wrapper's.
* **the intra-op thread count**, because the order the partial sums are reduced in
  depends on it. `tiny.en` scored 4.78% unpinned and 4.88% at `OMP_NUM_THREADS=1` on
  one machine, one model, one byte-identical 200-utterance subset.
* **the load average**, because latency and RTF are wall-clock and a contended host
  silently reports a slower machine than the one named in `cpu_model`.

Guarded rather than left to review: each of the three was omitted by someone who had
already thought carefully about provenance, which is what makes the omission the
likely failure mode rather than an unlikely one.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.benchmark_deps import load

BENCH = Path(__file__).resolve().parents[1] / "paper" / "benchmark"


@pytest.fixture(scope="module")
def common():
    return load("_common", "_common.py")


def test_provenance_names_what_decides_the_result(common):
    block = common.provenance("2026-01-01T00:00:00Z")
    for field in ("ctranslate2", "omp_num_threads", "load_average_1m",
                  "compute_type", "cpu_model", "logical_cpus"):
        assert field in block, (
            f"provenance dropped {field!r}; a figure quoted without it cannot be "
            "compared with a figure from another host"
        )


def test_thread_count_is_reported_as_set_or_unset_never_guessed(common, monkeypatch):
    """`unset` is a distinct answer from any number.

    CTranslate2 chooses its own thread count when the variable is absent, and that
    choice depends on the machine -- so recording a guessed number would assert a
    reproducibility the run does not have.
    """
    monkeypatch.delenv("OMP_NUM_THREADS", raising=False)
    assert common.provenance("t")["omp_num_threads"] == "unset"
    monkeypatch.setenv("OMP_NUM_THREADS", "4")
    assert common.provenance("t")["omp_num_threads"] == "4"


def test_load_average_is_a_number_on_every_platform(common):
    """Windows has no load average; the field must still exist and stay numeric.

    Returning `-1.0` rather than omitting the key keeps the block one shape across
    the five hosts `benchmark.yml` runs on, so a consumer never has to branch.
    """
    value = common.provenance("t")["load_average_1m"]
    assert isinstance(value, float)
    assert value == -1.0 or value >= 0.0
