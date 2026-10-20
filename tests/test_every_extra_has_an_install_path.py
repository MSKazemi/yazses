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
    "lsp": "the `yazses lsp` editor server, a command rather than a capability toggle",
    "silero": "`[meeting] vad_backend = \"silero\"`, a backend choice inside Meeting Mode",
    "voiceprint-resemblyzer": "an alternative `[voiceprint] backend`; its probe names "
                              "this extra (see test_feature_deps_cover_every_probe.py)",
    "diarization-pyannote": "an alternative `[recimport] backend`; its probe names this "
                            "extra (see test_feature_deps_cover_every_probe.py)",
}


def _extras() -> dict[str, list[str]]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["optional-dependencies"]


def _installable() -> set[str]:
    return {_requirement_name(p) for _mods, pkgs in _FEATURE_DEPS.values() for p in pkgs}


def _uncovered(requirements: list[str]) -> list[str]:
    have = _installable()
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


@pytest.mark.parametrize("extra", sorted(NOT_A_TOGGLE))
def test_every_exemption_is_real_explained_and_still_needed(extra):
    assert extra in _extras(), f"`{extra}` is no longer an extra; drop the exemption"
    assert len(NOT_A_TOGGLE[extra]) > 20, "an exemption needs a reason"
    if extra != "all":
        assert _uncovered(_extras()[extra]), (
            f"a feature now installs every package of `{extra}`; drop the exemption"
        )
