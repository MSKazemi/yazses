"""ADR-028 §7: every wired `_FEATURE_DEPS` slug has a packs.toml decision, every `pack`
extra exists in pyproject.toml, and no `pack` row serves only unwired slugs. Derived
from the three sources, never restated; an empty catalogue fails."""
from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from yazses.packs.catalog import (
    Decision,
    catalogue_problems,
    distribution,
    extra_for_packages,
    parse_decisions,
)
from yazses.system.features import _FEATURE_DEPS, _UNWIRED

ROOT = Path(__file__).resolve().parent.parent
EXTRAS = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
    "project"]["optional-dependencies"]
PACKS_TOML = ROOT / "packaging" / "packs" / "packs.toml"


def test_distribution_names_are_normalised() -> None:
    assert distribution("onnx-asr[cpu,hub]>=0.12") == "onnx-asr"
    assert distribution("Sherpa_ONNX>=1.13.6; sys_platform == 'win32'") == "sherpa-onnx"


def test_every_dependency_carrying_slug_maps_to_a_declared_extra() -> None:
    """Works today, before packs.toml exists: the derivation itself must cover the map."""
    assert _FEATURE_DEPS, "guard the guard: no feature declares dependencies"
    missing = {
        slug: pkgs for slug, (_m, pkgs) in _FEATURE_DEPS.items()
        if extra_for_packages(pkgs, EXTRAS) is None
    }
    assert not missing, f"no pyproject extra declares these features' packages: {missing}"


def test_the_derivation_picks_the_smallest_extra_and_never_all() -> None:
    extras = {"all": ["a", "b", "c"], "big": ["a", "b"], "small": ["a"]}
    assert extra_for_packages(["a>=1"], extras) == "small"
    assert extra_for_packages(["a", "b"], extras) == "big"
    assert extra_for_packages(["c"], extras) is None


def _deps():
    return {
        "stt-parakeet": (("onnx_asr",), ("onnx-asr[cpu,hub]>=0.12",)),
        "diarize": (("sherpa_onnx",), ("sherpa-onnx>=1", "sherpa-onnx-core>=1")),
        "voiceguard": (("speechbrain",), ("speechbrain>=1.1",)),
    }


_EXTRAS = {
    "parakeet": ["onnx-asr[cpu,hub]>=0.12"],
    "diarization": ["sherpa-onnx>=1", "sherpa-onnx-core>=1"],
    "voiceprint": ["speechbrain>=1.1"],
}


def test_a_complete_catalogue_has_no_problems() -> None:
    decisions = {
        "parakeet": Decision("parakeet", "pack", ("onnx_asr",)),
        "diarization": Decision("diarization", "pack", ("sherpa_onnx",)),
    }
    assert catalogue_problems(_deps(), {"voiceguard"}, _EXTRAS, decisions) == []


def test_a_wired_slug_without_a_decision_is_reported() -> None:
    decisions = {"parakeet": Decision("parakeet", "pack", ("onnx_asr",))}
    problems = catalogue_problems(_deps(), {"voiceguard"}, _EXTRAS, decisions)
    assert any("diarize" in p and "no packs.toml decision" in p for p in problems)


def test_a_pack_for_an_unknown_extra_or_an_unwired_slug_is_reported() -> None:
    decisions = {
        "parakeet": Decision("parakeet", "pack", ("onnx_asr",)),
        "diarization": Decision("diarization", "deferred", reason="collision"),
        "voiceprint": Decision("voiceprint", "pack", ("speechbrain",)),
        "nope": Decision("nope", "pack", ("x",)),
    }
    problems = catalogue_problems(_deps(), {"voiceguard"}, _EXTRAS, decisions)
    assert any("'nope', which is not a pyproject extra" in p for p in problems)
    assert any("packs 'voiceprint', but no wired feature uses it" in p for p in problems)


def test_an_empty_catalogue_fails() -> None:
    """Guard the guard: a loop over no decisions must not read as fine."""
    assert catalogue_problems(_deps(), set(), _EXTRAS, {})
    assert catalogue_problems({}, set(), _EXTRAS, {"x": Decision("x", "pack", ("x",))})


@pytest.mark.parametrize(
    "row",
    [
        {"decision": "maybe"},
        {"decision": "pack"},
        {"decision": "deferred"},
        {"decision": "pack", "entry_modules": ["m"], "approved_large": True},
        {"decision": "pack", "entry_modules": "m"},
    ],
)
def test_malformed_decisions_are_refused(row) -> None:
    with pytest.raises(ValueError):
        parse_decisions({"extras": {"x": row}})


def test_the_repository_packs_toml_agrees_with_features_and_extras() -> None:
    """The real check, once the build side has written packaging/packs/packs.toml."""
    if not PACKS_TOML.is_file():
        pytest.skip("packaging/packs/packs.toml is not in this tree yet (ADR-028 build side)")
    decisions = parse_decisions(tomllib.loads(PACKS_TOML.read_text(encoding="utf-8")))
    problems = catalogue_problems(_FEATURE_DEPS, _UNWIRED, EXTRAS, decisions)
    assert not problems, "\n".join(problems)
