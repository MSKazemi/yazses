"""The Intel macOS wheel ceiling must stay tied to the markers it describes (#264).

`system/intel_macos.py` tells an Intel-Mac user which Python versions will still
install YazSes. That advice is only worth printing while it is true, and it is
built on two facts that live somewhere else: the `onnxruntime` cap in
`pyproject.toml`, and `requires-python`. A number copied out of a manifest and
never compared to it is the thing that goes quietly stale — and stale here is
worse than silent, because the row is *reassuring*.

So these tests do not re-assert the constants. They check the constants against the
manifest, and check the behaviour the row is there to produce.

Note what is deliberately NOT tested: that Python 3.14 really has no onnxruntime
x86_64 wheel. That is a fact about PyPI on a given day, and asserting it would make
the suite fail when upstream *fixes* Intel macOS — the one outcome nobody should be
warned about. `tests/test_intel_macos_wheels_resolve.py` owns the resolution side.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from yazses.system.intel_macos import (
    BASE_MAX_MINOR,
    EXTRAS_MAX_MINOR,
    ceiling_advice,
    is_intel_mac,
)

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"


def _pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def test_the_intel_cap_this_advice_describes_still_exists() -> None:
    """If the onnxruntime cap goes, the advice is describing nothing.

    Removing the cap is exactly how #264 would be resolved by dropping Intel macOS.
    That is a legitimate decision — but it must take this row with it, rather than
    leaving `doctor` telling Intel users about a ceiling the manifest no longer has.
    """
    text = PYPROJECT.read_text(encoding="utf-8")
    assert "onnxruntime" in text
    capped = [
        line for line in text.splitlines()
        if "onnxruntime" in line and "<1.24" in line
        and "platform_machine == 'x86_64'" in line
    ]
    assert capped, (
        "system/intel_macos.py explains an Intel-macOS onnxruntime ceiling that "
        "pyproject.toml no longer has. Either restore the cap, or delete the doctor "
        "row and the docs paragraph that describe it."
    )


def test_the_ceiling_is_not_below_the_python_we_claim_to_support() -> None:
    """`requires-python` promises a floor; the ceiling must leave room above it."""
    floor = _pyproject()["project"]["requires-python"]
    assert floor.startswith(">=3.")
    floor_minor = int(floor.removeprefix(">=3.").split(",")[0].strip())
    assert floor_minor <= EXTRAS_MAX_MINOR <= BASE_MAX_MINOR, (
        f"requires-python floors at 3.{floor_minor}, but the Intel ceiling is "
        f"base 3.{BASE_MAX_MINOR} / extras 3.{EXTRAS_MAX_MINOR}. If the floor ever "
        f"rises above the ceiling, Intel macOS is unsupported in fact and the "
        f"support matrix has to say so rather than this row hinting at it."
    )


def test_extras_cannot_outlast_the_base_install() -> None:
    """`[all]` includes the base, so its ceiling can never be the higher one."""
    assert EXTRAS_MAX_MINOR <= BASE_MAX_MINOR


@pytest.mark.parametrize(
    "sys_platform,machine",
    [
        ("darwin", "arm64"),   # Apple silicon — none of this applies
        ("linux", "x86_64"),   # same CPU, entirely different wheels
        ("win32", "AMD64"),
        ("freebsd14", "x86_64"),
    ],
)
def test_no_row_anywhere_but_an_intel_mac(sys_platform: str, machine: str) -> None:
    """A warning shown where it is irrelevant is one people learn to scroll past."""
    assert not is_intel_mac(sys_platform, machine)
    assert ceiling_advice(sys_platform, machine, (3, 14)) is None


@pytest.mark.parametrize("minor", [11, 12, 13, 14, 15])
def test_a_working_install_is_never_reported_as_a_failure(minor: int) -> None:
    """This row is advice about the *next* install, not a verdict on this one.

    The code cannot run unless the resolution that produced it succeeded, so FAIL
    would be a false statement about the machine it is printed on — and a false
    FAIL teaches the reader to disbelieve the true ones.
    """
    row = ceiling_advice("darwin", "x86_64", (3, minor))
    assert row is not None
    name, status, detail = row
    assert name == "Intel macOS"
    assert status in {"OK", "WARN"}
    assert detail


def test_within_the_ceiling_is_ok_and_past_it_warns() -> None:
    assert ceiling_advice("darwin", "x86_64", (3, EXTRAS_MAX_MINOR))[1] == "OK"
    assert ceiling_advice("darwin", "x86_64", (3, EXTRAS_MAX_MINOR + 1))[1] == "WARN"
    assert ceiling_advice("darwin", "x86_64", (3, BASE_MAX_MINOR + 1))[1] == "WARN"


def test_the_warning_blames_upstream_and_not_yazses() -> None:
    """The resolver error a user actually sees names onnxruntime and looks like our
    packaging bug. The row's whole job is to pre-empt that reading."""
    past_base = ceiling_advice("darwin", "x86_64", (3, BASE_MAX_MINOR + 1))[2]
    assert "onnxruntime" in past_base
    past_extras = ceiling_advice("darwin", "x86_64", (3, EXTRAS_MAX_MINOR + 1))[2]
    assert "torch" in past_extras
    # And it must say what to do, not merely what is wrong.
    assert str(BASE_MAX_MINOR) in past_base


def test_doctor_actually_calls_this() -> None:
    """A pure function nothing imports is the failure mode this project logs as an
    orphan. Cheaper to assert the wiring than to rediscover it."""
    source = (ROOT / "src" / "yazses" / "system" / "doctor.py").read_text(encoding="utf-8")
    assert "ceiling_advice" in source
