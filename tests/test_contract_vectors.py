"""The cross-platform contract vectors must stay true to the shipped behaviour.

`contract/vectors/*.json` is the normative definition of behaviour that every YazSes
implementation shares — this Python desktop today, the Kotlin Android app next, iOS
after that (ADR-MOB-008, `docs/mobile/contract.md`). The Android port reads these exact
files as its test data, so a contributor can implement a module in Kotlin without
reading a line of Python and still know when it is correct.

This test is the guard half of generate-and-guard: it re-runs every case against the
shipped implementation. If you change shared behaviour, this goes red until you run

    uv run python scripts/gen-contract-vectors.py

...and **read the resulting diff**. A changed expectation is a behaviour change that
every other platform now has to follow — it is not a formatting artefact, and it must
not be regenerated on autopilot.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
GEN = ROOT / "scripts" / "gen-contract-vectors.py"
VECTOR_DIR = ROOT / "contract" / "vectors"


def _load_gen():
    spec = importlib.util.spec_from_file_location("gen_contract_vectors", GEN)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def gen():
    return _load_gen()


def _load_vector_files() -> list[tuple[str, dict[str, Any]]]:
    return [(p.name, json.loads(p.read_text(encoding="utf-8")))
            for p in sorted(VECTOR_DIR.glob("*.json"))]


def _all_cases() -> list[tuple[str, str, dict[str, Any]]]:
    out = []
    for fname, doc in _load_vector_files():
        for case in doc["cases"]:
            out.append((fname, doc["unit"], case))
    return out


VECTOR_FILES = _load_vector_files()
ALL_CASES = _all_cases()


def test_vector_files_exist():
    """A missing contract is worse than a failing one — it fails silently."""
    assert VECTOR_FILES, f"no vector files in {VECTOR_DIR}"


@pytest.mark.parametrize(
    "fname,unit,case",
    ALL_CASES,
    ids=[f"{f.removesuffix('.json')}:{c['id']}" for f, _, c in ALL_CASES],
)
def test_case_matches_shipped_behaviour(gen, fname, unit, case):
    _source, runner = gen.UNITS[unit]
    actual = runner(case["input"], case["options"])
    assert actual == case["expected"], (
        f"\n{fname} case '{case['id']}' no longer matches the implementation."
        f"\n  {case['description']}"
        f"\n  input:    {case['input']!r}"
        f"\n  expected: {case['expected']!r}"
        f"\n  actual:   {actual!r}"
        f"\n\nIf this change is intended, regenerate and READ THE DIFF:"
        f"\n  uv run python scripts/gen-contract-vectors.py"
        f"\nEvery other platform implements what these files say."
    )


@pytest.mark.parametrize("fname,doc", VECTOR_FILES, ids=[f for f, _ in VECTOR_FILES])
def test_vector_file_is_byte_identical_to_regeneration(gen, fname, doc):
    """Catches a hand-edited expectation, and a case added to one side only."""
    rendered = gen.render(gen.build(doc["unit"]))
    on_disk = (VECTOR_DIR / fname).read_text(encoding="utf-8")
    assert on_disk == rendered, (
        f"{fname} is out of date — run: uv run python scripts/gen-contract-vectors.py"
    )


@pytest.mark.parametrize("fname,doc", VECTOR_FILES, ids=[f for f, _ in VECTOR_FILES])
def test_every_case_is_documented_and_uniquely_identified(fname, doc):
    ids = [c["id"] for c in doc["cases"]]
    assert len(ids) == len(set(ids)), f"{fname} has duplicate case ids"
    for case in doc["cases"]:
        assert case["id"] and case["id"] == case["id"].lower(), (
            f"{fname}: case id must be lower-case kebab: {case['id']!r}"
        )
        assert case["description"].strip(), (
            f"{fname}: case {case['id']!r} has no description — a case whose purpose "
            f"is not written down cannot be safely changed by anyone else"
        )


@pytest.mark.parametrize("fname,doc", VECTOR_FILES, ids=[f for f, _ in VECTOR_FILES])
def test_declared_contract_version_matches(fname, doc):
    version = (ROOT / "contract" / "VERSION").read_text().strip()
    assert doc["contract_version"] == version, (
        f"{fname} was generated under contract {doc['contract_version']}, "
        f"but contract/VERSION says {version}"
    )


def test_generator_and_vectors_cover_the_same_units(gen):
    on_disk = {doc["unit"] for _, doc in VECTOR_FILES}
    declared = set(gen.UNITS)
    assert on_disk == declared, (
        "a unit exists in the generator but not on disk (or vice versa) — "
        f"on disk: {sorted(on_disk)}, declared: {sorted(declared)}"
    )
