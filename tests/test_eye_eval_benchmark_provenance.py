"""The paper benchmark's provenance maps onto the eye-eval envelope, and is not described twice.

#421's last acceptance criterion: "existing paper benchmark provenance can be mapped/reused
instead of duplicated". `yazses.eyeeval.provenance` cannot import
`paper/benchmark/_common.py` (it is not shipped, and it imports numpy and psutil at module
scope), so the mapping is written down as data. These tests hold that data against the
benchmark's own source in both directions, and run every provenance block committed under
`paper/results/` through the mapping into a result the schema accepts.

Pure: the benchmark module is parsed, never imported, and no camera, clock or network is
touched.
"""

from __future__ import annotations

import ast
import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from yazses.eyeeval import (
    build_result,
    generate_task,
    privacy_problems,
    synthetic_records,
    validate_result,
)
from yazses.eyeeval.provenance import (
    BENCHMARK_FIELDS,
    BENCHMARK_FIELDS_NOT_CARRIED,
    Provenance,
    as_sections,
    from_benchmark,
)

ROOT = Path(__file__).resolve().parents[1]
COMMON = ROOT / "paper" / "benchmark" / "_common.py"
RESULTS = ROOT / "paper" / "results"

#: A block exactly as `_common.provenance()` wrote one into `paper/results/` (values copied
#: from a committed artifact, so the shape is the real one rather than an invented one).
BLOCK: dict[str, Any] = {
    "timestamp": "2026-07-30T21:17:57Z",
    "cpu_model": "13th Gen Intel(R) Core(TM) i7-1370P",
    "logical_cpus": 20,
    "ram_gb": 33.3,
    "os": "Ubuntu 24.04.4 LTS",
    "kernel": "7.0.0-28-generic",
    "python": "3.12.3",
    "faster_whisper": "1.2.1",
    "yazses": "2.12.0.dev4",
    "numpy": "2.4.6",
    "compute_type": "int8",
    "device": "cpu",
}


def _benchmark_dataclass_fields() -> list[str]:
    """Field names of `Provenance` in `_common.py`, read from its source."""
    tree = ast.parse(COMMON.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Provenance":
            return [
                stmt.target.id
                for stmt in node.body
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
            ]
    raise AssertionError(f"no `class Provenance` in {COMMON}")


def _committed_blocks() -> list[tuple[str, dict[str, Any]]]:
    out = []
    for path in sorted(RESULTS.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        block = doc.get("provenance") if isinstance(doc, dict) else None
        if isinstance(block, dict):
            out.append((path.name, block))
    return out


def _envelope(prov: Provenance) -> dict[str, Any]:
    task = generate_task("gaze_routing_4_pane")
    return build_result(
        task=task, records=synthetic_records(task), provenance=prov, study_mode="synthetic",
        timestamp=BLOCK["timestamp"], camera_class="none", capture_mode="synthetic_replay",
        records_source="synthetic",
    )


# --- the mapping is complete, in both directions ----------------------------------------


def test_the_benchmark_field_list_is_read_and_is_not_empty() -> None:
    """A parser that found nothing would make the completeness test below vacuous."""
    fields = _benchmark_dataclass_fields()
    assert len(fields) >= 10
    assert {"cpu_model", "os", "kernel", "python"} <= set(fields)


def test_every_benchmark_field_is_carried_or_left_out_with_a_reason() -> None:
    """A field added to `_common.Provenance` must be placed here, and a removed one dropped."""
    fields = set(_benchmark_dataclass_fields())
    placed = set(BENCHMARK_FIELDS) | set(BENCHMARK_FIELDS_NOT_CARRIED)
    assert fields - placed == set(), "benchmark fields with no mapping and no stated reason"
    assert placed - fields == set(), "mapping names fields the benchmark no longer has"
    assert set(BENCHMARK_FIELDS).isdisjoint(BENCHMARK_FIELDS_NOT_CARRIED)
    assert all(reason.strip() for reason in BENCHMARK_FIELDS_NOT_CARRIED.values())


def test_every_mapping_target_is_a_real_provenance_field() -> None:
    names = {f.name for f in dataclasses.fields(Provenance)}
    for source, target in BENCHMARK_FIELDS.items():
        head = target.split(".", 1)[0]
        assert head in names, f"{source} -> {target}: no such Provenance field"


# --- the mapping itself -------------------------------------------------------------------


def test_a_real_block_maps_onto_the_matching_fields() -> None:
    prov = from_benchmark(BLOCK)
    assert prov.cpu_model == BLOCK["cpu_model"]
    assert prov.logical_cpus == 20
    assert prov.ram_gb == 33.3
    assert prov.os_name == "Ubuntu 24.04.4 LTS"
    assert prov.kernel == "7.0.0-28-generic"
    assert prov.python_version == "3.12.3"
    assert prov.yazses_version == "2.12.0.dev4"
    assert prov.packages == {"faster-whisper": "1.2.1", "numpy": "2.4.6"}


def test_what_the_benchmark_never_recorded_is_not_guessed() -> None:
    """`os` is one opaque name; splitting it into name and version would be a guess."""
    prov = from_benchmark(BLOCK)
    assert prov.os_version == "unknown"
    assert prov.arch == "unknown"
    assert prov.git_commit is None
    assert prov.displays == ()
    assert as_sections(prov)["display"]["display_count"] == 0


def test_an_unknown_package_version_is_left_out_not_recorded() -> None:
    prov = from_benchmark({**BLOCK, "ctranslate2": "unknown", "numpy": ""})
    assert "ctranslate2" not in prov.packages
    assert "numpy" not in prov.packages


def test_an_unread_ram_size_stays_absent_rather_than_zero() -> None:
    assert from_benchmark({**BLOCK, "ram_gb": None}).ram_gb is None
    with pytest.raises(ValueError, match="ram_gb"):
        from_benchmark({**BLOCK, "ram_gb": 0})


def test_free_text_fields_never_reach_the_envelope() -> None:
    """`argv`, `corpus` and keys the mapping does not name (`shard_argv`) are not carried."""
    leaky = {
        **BLOCK,
        "argv": "paper/benchmark/bench_wer.py --corpus /home/someone/LibriSpeech",
        "shard_argv": ["/home/someone/run.sh"],
        "corpus": {"path": "/home/someone/LibriSpeech", "digest": "abc"},
    }
    text = json.dumps(_envelope(from_benchmark(leaky)))
    assert "/home/someone" not in text
    assert "someone" not in text


# --- input that cannot be read is refused, not defaulted ---------------------------------


@pytest.mark.parametrize("bad", [None, [], "provenance", 3, {}])
def test_a_block_that_is_not_one_is_refused(bad: Any) -> None:
    """`{}` especially: it must not become an all-"unknown" provenance that validates."""
    with pytest.raises(ValueError):
        from_benchmark(bad)


def test_a_block_with_none_of_the_mapped_fields_is_refused() -> None:
    with pytest.raises(ValueError, match="none of the benchmark provenance fields"):
        from_benchmark({"timestamp": BLOCK["timestamp"], "argv": "x"})


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("logical_cpus", True),
        ("logical_cpus", "20"),
        ("logical_cpus", -1),
        ("ram_gb", float("nan")),
        ("ram_gb", float("inf")),
        ("ram_gb", "33.3"),
        ("ram_gb", False),
        ("cpu_model", 5),
        ("os", None),
        ("numpy", 2),
    ],
)
def test_a_field_of_the_wrong_type_is_refused_by_name(key: str, value: Any) -> None:
    with pytest.raises(ValueError, match=key):
        from_benchmark({**BLOCK, key: value})


# --- every committed block maps into a result the schema accepts --------------------------


def test_the_committed_benchmark_walk_is_not_vacuous() -> None:
    assert len(_committed_blocks()) >= 10


def test_every_committed_benchmark_block_maps_into_a_valid_private_result() -> None:
    for name, block in _committed_blocks():
        doc = _envelope(from_benchmark(block))
        assert validate_result(doc) == [], name
        assert privacy_problems(doc) == [], name
