"""The pure decisions behind a feature install: channel, constraints, markers, undo.

`system/install_txn.py` decides; `system/deps.py` runs. Every case here is a string or
a dict, so none needs a network, a package manager or an optional dependency. The
behaviour they encode was first reproduced offline against the real tools (uv 0.12.21,
pipx 1.4.3, hand-built wheels): a feature downgrading a base dependency with exit 0,
pipx ignoring markers, and a pip-installed package vanishing on `pipx reinstall`.
"""

from __future__ import annotations

import types

import pytest

from yazses.system import install_txn as t

# ---- the channel ---------------------------------------------------------------

_NONE = dict(snap=False, frozen=False, uv_receipt=False, pipx_venv=False,
             editable=False, in_venv=False)


@pytest.mark.parametrize(
    "facts, channel",
    [
        ({}, t.SYSTEM),
        ({"in_venv": True}, t.VENV),
        ({"in_venv": True, "editable": True}, t.EDITABLE),
        ({"in_venv": True, "pipx_venv": True}, t.PIPX),
        ({"in_venv": True, "uv_receipt": True}, t.UV_TOOL),
        ({"frozen": True, "in_venv": True}, t.FROZEN),
        ({"snap": True, "frozen": True}, t.SNAP),
    ],
)
def test_the_most_specific_fact_names_the_channel(facts, channel):
    assert t.classify(**{**_NONE, **facts}) == channel


def test_every_channel_says_how_it_installs_and_whether_it_can():
    assert set(t.CHANNELS) == {t.SNAP, t.FROZEN, t.UV_TOOL, t.PIPX, t.EDITABLE, t.VENV, t.SYSTEM}
    for key, ch in t.CHANNELS.items():
        assert ch.key == key and ch.installer
        assert ch.can_install == bool(ch.survives), key


def test_a_channel_that_can_install_is_one_classify_can_return():
    reachable = {
        t.classify(**{**_NONE, **{k: True}}) for k in _NONE
    } | {t.classify(**_NONE)}
    assert reachable == set(t.CHANNELS)


# ---- YazSes's own requirements -------------------------------------------------

REQUIRES = [
    "faster-whisper>=1.2.1",
    "numpy>=2.4.6",
    "typer>=0.26.8",
    'evdev>=1.9.3; sys_platform == "linux"',
    'pywin32>=312; sys_platform == "win32"',
    "kokoro-onnx>=0.5.0; extra == 'tts'",
    "onnx-asr[cpu,hub]>=0.12; extra == 'parakeet'",
    "PySide6>=6.11.1; extra == 'desktop'",
    "PySide6>=6.11.1; extra == 'all'",
    "cryptography",
]


def test_the_base_is_the_unconditional_requirements_on_this_platform():
    base = t.base_requirements(REQUIRES)
    assert "numpy>=2.4.6" in base and "cryptography" in base
    assert not any("extra ==" in r for r in base), "an extra is what a feature may add"
    import sys

    assert any("evdev" in r for r in base) == (sys.platform == "linux")
    assert any("pywin32" in r for r in base) == (sys.platform == "win32")


def test_constraint_lines_hold_ranges_without_extras_or_markers():
    lines = t.constraint_lines(["onnx-asr[cpu,hub]>=0.12", "numpy>=2.4.6", "cryptography"])
    assert lines == ["onnx-asr>=0.12", "numpy>=2.4.6"], (
        "pip rejects extras in a constraint, and a bare name constrains nothing"
    )


def test_unsatisfied_names_a_downgrade_and_a_removal_but_not_a_prerelease():
    base = ["numpy>=2.4.6", "platformdirs>=4.10.0", "typer>=0.26.8"]
    installed = {"numpy": "1.26.4", "typer": "0.27.0rc1"}
    problems = t.unsatisfied(base, installed)
    assert any("numpy 1.26.4" in p for p in problems)
    assert any("platformdirs is missing" in p for p in problems)
    assert not any("typer" in p for p in problems)


def test_unsatisfied_is_empty_for_a_healthy_set():
    assert t.unsatisfied(["numpy>=2.4.6"], {"numpy": "2.4.6"}) == []


# ---- markers, for the installer that ignores them ------------------------------

_ONNX_PAIR = (
    "onnxruntime>=1.27.0; sys_platform != 'darwin' or platform_machine != 'x86_64'",
    "onnxruntime>=1.23.2,<1.24; sys_platform == 'darwin' and platform_machine == 'x86_64'",
)


@pytest.mark.parametrize(
    "env, expected",
    [
        ({"sys_platform": "linux", "platform_machine": "x86_64"}, ["onnxruntime>=1.27.0"]),
        ({"sys_platform": "darwin", "platform_machine": "arm64"}, ["onnxruntime>=1.27.0"]),
        ({"sys_platform": "darwin", "platform_machine": "x86_64"},
         ["onnxruntime<1.24,>=1.23.2"]),
    ],
)
def test_exactly_one_of_the_onnxruntime_pair_survives_on_each_platform(env, expected):
    """pipx would ask for both halves, which no version satisfies."""
    from packaging.markers import default_environment

    got = t.applicable(_ONNX_PAIR, {**default_environment(), **env})
    assert got == expected


def test_a_spec_without_a_marker_or_that_cannot_be_parsed_is_kept():
    assert t.applicable(["kokoro-onnx>=0.5.0", "not a [valid spec"]) == [
        "kokoro-onnx>=0.5.0", "not a [valid spec",
    ]


def test_the_extras_that_declare_a_package_are_found_from_metadata():
    extras = t.extras_providing(["kokoro-onnx>=0.5.0", "PySide6>=6.11.1"], REQUIRES)
    assert extras == ["tts", "desktop"], "`all` is never suggested"


# ---- snapshot and undo -----------------------------------------------------------


def _dist(name, version):
    return types.SimpleNamespace(metadata={"Name": name}, version=version)


def test_snapshot_canonicalises_and_skips_broken_records():
    class Broken:
        @property
        def metadata(self):
            raise OSError("unreadable METADATA")

    snap = t.snapshot([_dist("PySide6", "6.11.1"), _dist("Foo_Bar", "1"), Broken(),
                       _dist("", "1"), _dist("foo-bar", "2")])
    assert snap == {"pyside6": "6.11.1", "foo-bar": "1"}, "first copy wins, as for imports"


def test_diff_and_restore_specs_undo_every_kind_of_change():
    before = {"numpy": "2.4.6", "torch": "2.9.0", "yazses": "2.43.2", "keep": "1"}
    after = {"numpy": "1.26.4", "speechbrain": "1.1", "yazses": "2.43.3", "keep": "1"}
    change = t.diff(before, after)
    assert change and change.added == ("speechbrain",)
    assert change.removed == (("torch", "2.9.0"),)
    assert ("numpy", "2.4.6", "1.26.4") in change.changed
    uninstall, reinstall = t.restore_specs(change)
    assert uninstall == ["speechbrain"]
    assert sorted(reinstall) == ["numpy==2.4.6", "torch==2.9.0"], (
        "yazses itself is never reinstalled by version: a checkout cannot be"
    )
    assert "numpy 2.4.6→1.26.4" in change.describe()


def test_no_change_is_falsy_and_says_nothing():
    change = t.diff({"a": "1"}, {"a": "1"})
    assert not change and change.describe() == "nothing"
    assert t.restore_specs(change) == ([], [])
