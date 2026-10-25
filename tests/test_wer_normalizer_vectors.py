"""The replay target for the Kotlin WER normaliser must stay true to Whisper's (#677).

``android/core/bench/src/test/resources/wer-normalizer-vectors.json`` is Whisper's English text
normaliser, frozen as input/expected pairs. The Android port (``:core:bench``) replays them, so
the phone and the desktop benchmark (``paper/benchmark/bench_wer.py``) score WER after the same
normalisation. This is the guard half: it re-runs the real package over the same inputs and
fails if the committed file drifted. It needs the ``benchmark`` dependency group, which a
plain ``uv sync`` does not install, so it skips there and runs in the ``Benchmark harness
tests`` CI job.

If it fails because the package was upgraded, that is a behaviour change the Kotlin port must
follow: regenerate, READ the diff, and update the port.

    uv sync --group benchmark
    uv run python scripts/gen-wer-normalizer-vectors.py
"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

pytest.importorskip(
    "whisper_normalizer",
    reason="the `benchmark` dependency group is not installed (uv sync --group benchmark)",
)

ROOT = Path(__file__).resolve().parent.parent
GEN = ROOT / "scripts" / "gen-wer-normalizer-vectors.py"
VECTORS = ROOT / "android" / "core" / "bench" / "src" / "test" / "resources" / "wer-normalizer-vectors.json"
SPELLING = ROOT / "android" / "core" / "bench" / "src" / "main" / "resources" / "english-spelling.tsv"


@pytest.fixture(scope="module")
def gen():
    spec = importlib.util.spec_from_file_location("gen_wer_normalizer_vectors", GEN)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def doc():
    return json.loads(VECTORS.read_text(encoding="utf-8"))


def test_committed_vectors_are_byte_identical_to_regeneration(gen):
    """Catches a hand-edited expectation, a changed corpus, and a package upgrade."""
    assert VECTORS.read_text(encoding="utf-8") == gen.render(gen.build()), (
        "wer-normalizer-vectors.json is out of date. Run "
        "`uv run python scripts/gen-wer-normalizer-vectors.py`, read the diff, and make the "
        "Kotlin port follow any behaviour change."
    )


def test_shipped_spelling_table_is_the_oracles_own_mapping(gen):
    """The port ships this table, so it must be exactly what Whisper's normaliser maps."""
    assert SPELLING.read_text(encoding="utf-8") == gen.build_spelling(), (
        "english-spelling.tsv is out of date; run scripts/gen-wer-normalizer-vectors.py"
    )
    rows = [line.split("\t") for line in SPELLING.read_text(encoding="utf-8").splitlines()]
    assert len(rows) > 1000 and all(len(r) == 2 for r in rows)


def test_the_oracle_is_the_normaliser_the_desktop_benchmark_scores_with(doc):
    """If the benchmark ever scores with something else, this file stops being the target."""
    bench = (ROOT / "paper" / "benchmark" / "bench_wer.py").read_text(encoding="utf-8")
    assert re.search(r"from whisper_normalizer\.english import EnglishTextNormalizer", bench) or (
        "EnglishTextNormalizer" in bench and "whisper_normalizer" in bench
    ), "paper/benchmark/bench_wer.py no longer uses whisper_normalizer's EnglishTextNormalizer"
    assert doc["oracle"]["class"] == "whisper_normalizer.english.EnglishTextNormalizer"


def test_every_case_is_identified_and_documented(doc):
    ids = [c["id"] for c in doc["cases"]]
    assert len(ids) == len(set(ids)), "duplicate case ids"
    for c in doc["cases"]:
        assert c["id"] == c["id"].lower(), f"case id must be lower-case kebab: {c['id']!r}"
        assert c["description"].strip(), f"case {c['id']!r} has no description"
        assert isinstance(c["input"], str) and isinstance(c["expected"], str)


@pytest.mark.parametrize(
    "prefix,minimum",
    [("num-", 30), ("ord-", 8), ("digits-", 15), ("cur-", 10), ("spell-", 10), ("title-", 5),
     ("abbrev-", 6), ("sym-", 8), ("acc-", 5), ("contraction-", 8), ("hesitation-", 4),
     ("dict-", 5), ("random-", 300)],
)
def test_the_corpus_covers_every_rule_family(doc, prefix, minimum):
    """A corpus that quietly shrinks is a port that quietly diverges."""
    count = sum(1 for c in doc["cases"] if c["id"].startswith(prefix))
    assert count >= minimum, f"only {count} '{prefix}*' cases; the corpus needs at least {minimum}"


def test_the_oracle_actually_normalises(doc):
    """Guards against a vacuous file: some cases must change, and some must come out empty."""
    changed = sum(1 for c in doc["cases"] if c["expected"] != c["input"])
    assert changed > len(doc["cases"]) * 0.8
    assert any(c["expected"] == "" for c in doc["cases"])
