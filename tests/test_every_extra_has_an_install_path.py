"""Every optional extra is installable by `features enable`, or says why it is not.

The existing guards run one way: a feature's pins must come from an extra
(`test_feature_pins_match_the_extras.py`), and a backend probe that names an extra
must have a feature that installs it (`test_feature_deps_cover_every_probe.py`). The
other direction was open. A contributor who adds a new extra for a new feature and
forgets its `_FEATURE_DEPS` entry ships a toggle that writes `enabled = true`,
installs nothing, and leaves the feature dead — the `denoise` bug, exactly.

So this derives both sides — the extras from `pyproject.toml`, the installable
packages from the feature registry — with no hand-written list of either. The only
hand-kept data is the exemption map, and each entry must carry a reason, name a real
extra, and still be uncovered (a stale exemption fails too).
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from yazses.system.deps import _requirement_name
from yazses.system.features import _FEATURE_DEPS

ROOT = Path(__file__).resolve().parents[1]

#: Extras deliberately not installed through a feature toggle, and why.
NOT_A_TOGGLE: dict[str, str] = {
    "all": "the union of every other extra, for people who want everything at once",
    "ble": "EMG over Bluetooth, selected by `[emg] ble_address`, not a toggle; "
           "`yazses doctor`'s EMG BLE row names the install",
    "emg": "USB EMG, selected by `[emg] device_port`, not a toggle",
    "emg-band": "the brainflow band source for EMG, a hardware choice, not a toggle",
    "lsl": "the Lab Streaming Layer biosignal source, a hardware choice, not a toggle",
    "xdf": "replays LabRecorder .xdf files for the biosignal switch, a file format, not a toggle",
    "lsp": "the `yazses lsp` editor server, a command rather than a capability toggle",
    "silero": "`[meeting] vad_backend = \"silero\"`, a backend choice inside Meeting Mode",
    "voiceprint-resemblyzer": "an alternative `[voiceprint] backend`; its probe names "
                              "this extra (see test_feature_deps_cover_every_probe.py)",
    "diarization-pyannote": "an alternative `[recimport] backend`; its probe names this "
                            "extra (see test_feature_deps_cover_every_probe.py)",
}


#: Requirements an extra repeats purely to anchor a `[tool.uv.sources]` index -- uv
#: applies a source only to a *direct* dependency (measured on 0.12.21: with the torch
#: source declared and torch absent from every extra, `uv lock` left torch on pypi.org,
#: the CUDA build, with no warning). Each is already pulled by the named package of the
#: same extra, which a feature *does* install, and `system/deps.py` carries the index to
#: that install -- so a toggle installs nothing less for leaving them out. Not a free
#: pass: `test_every_anchor_is_sourced_and_already_pulled` fails the day the source or
#: the pulling package goes away.
ANCHORS: dict[str, str] = {
    "torch": "speechbrain",
    "torchaudio": "speechbrain",
}


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _extras() -> dict[str, list[str]]:
    return _pyproject()["project"]["optional-dependencies"]


def _installable() -> set[str]:
    return {_requirement_name(p) for _mods, pkgs in _FEATURE_DEPS.values() for p in pkgs}


def _uncovered(requirements: list[str]) -> list[str]:
    have = _installable() | set(ANCHORS)
    return sorted({_requirement_name(r) for r in requirements} - have)


def test_there_is_something_to_check():
    assert len(_extras()) > 5 and len(_installable()) > 5


@pytest.mark.parametrize("extra", sorted(set(_extras()) - set(NOT_A_TOGGLE)))
def test_every_toggle_extra_is_installed_by_some_feature(extra):
    missing = _uncovered(_extras()[extra])
    assert not missing, (
        f"The `{extra}` extra declares {missing}, but no feature in "
        "`system/features.py::_FEATURE_DEPS` installs them, so `yazses features "
        "enable` would turn the capability on and install nothing. Add the feature's "
        "entry, or add the extra to NOT_A_TOGGLE here with the reason it is not a toggle."
    )


@pytest.mark.parametrize("anchor,puller", sorted(ANCHORS.items()))
def test_every_anchor_is_sourced_and_already_pulled(anchor, puller):
    """An anchor earns its exemption twice over, and both halves are read from files:
    it has a `[tool.uv.sources]` entry (the reason it is spelled out), and `uv.lock`
    records it as a dependency of *puller*, which some feature installs."""
    sources = _pyproject()["tool"]["uv"]["sources"]
    assert anchor in sources, f"{anchor} is in ANCHORS but has no [tool.uv.sources] entry"
    assert puller in _installable(), f"{puller} is not installed by any feature"
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    blocks = [b for b in lock.split("\n[[package]]\n") if b.startswith(f'name = "{puller}"\n')]
    assert blocks, f"{puller} is not in uv.lock"
    assert any(f'{{ name = "{anchor}"' in b for b in blocks), (
        f"uv.lock no longer records {anchor} as a dependency of {puller}; the extra "
        f"now installs {anchor} on its own account and a feature must declare it"
    )
    extras_with_anchor = [
        e for e, reqs in _extras().items() if anchor in {_requirement_name(r) for r in reqs}
    ]
    for extra in extras_with_anchor:
        assert puller in {_requirement_name(r) for r in _extras()[extra]}, (
            f"[{extra}] lists the anchor {anchor} without {puller}, the package it rides on"
        )


@pytest.mark.parametrize("extra", sorted(NOT_A_TOGGLE))
def test_every_exemption_is_real_explained_and_still_needed(extra):
    assert extra in _extras(), f"`{extra}` is no longer an extra; drop the exemption"
    assert len(NOT_A_TOGGLE[extra]) > 20, "an exemption needs a reason"
    if extra != "all":
        assert _uncovered(_extras()[extra]), (
            f"a feature now installs every package of `{extra}`; drop the exemption"
        )
