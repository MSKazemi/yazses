"""The crippled-snap detector.

Both interfaces YazSes needs are manual-connect and a snap cannot connect its
own, so an install can be complete, healthy-looking and totally deaf. These
tests pin the three-valued answer, because the two ways of collapsing it to a
boolean are each wrong in their own direction.
"""

from __future__ import annotations

import subprocess

import pytest

from yazses.system import snap

SNAP_ENV = {"SNAP_NAME": "yazses", "SNAP": "/snap/yazses/current"}


def _fake_run(returncode: int, *, raises: type[BaseException] | None = None):
    def run(cmd, **kwargs):
        if raises is not None:
            raise raises("boom")
        return subprocess.CompletedProcess(cmd, returncode, b"", b"")

    return run


@pytest.fixture
def in_snap(monkeypatch):
    monkeypatch.setattr(snap.shutil, "which", lambda name: f"/usr/bin/{name}")
    return monkeypatch


def test_outside_a_snap_the_answer_is_unknown_not_false() -> None:
    """A pipx user has no interfaces; reporting them "disconnected" is a lie."""
    assert snap.interface_connected("audio-record", {}) is None


def test_connected_when_snapctl_exits_zero(in_snap) -> None:
    in_snap.setattr(snap.subprocess, "run", _fake_run(0))
    assert snap.interface_connected("audio-record", SNAP_ENV) is True


def test_disconnected_when_snapctl_exits_one(in_snap) -> None:
    in_snap.setattr(snap.subprocess, "run", _fake_run(1))
    assert snap.interface_connected("raw-input", SNAP_ENV) is False


@pytest.mark.parametrize("code", [2, 127])
def test_any_other_exit_code_is_unknown(in_snap, code: int) -> None:
    """snapd too old for `is-connected` must not read as "disconnected"."""
    in_snap.setattr(snap.subprocess, "run", _fake_run(code))
    assert snap.interface_connected("raw-input", SNAP_ENV) is None


def test_a_raising_snapctl_is_unknown(in_snap) -> None:
    in_snap.setattr(snap.subprocess, "run", _fake_run(0, raises=OSError))
    assert snap.interface_connected("raw-input", SNAP_ENV) is None


def test_missing_snapctl_is_unknown(monkeypatch) -> None:
    monkeypatch.setattr(snap.shutil, "which", lambda name: None)
    assert snap.interface_connected("raw-input", SNAP_ENV) is None


def test_missing_interfaces_lists_only_definite_failures(in_snap) -> None:
    in_snap.setattr(
        snap,
        "interface_connected",
        lambda plug, env=None: {"audio-record": False, "raw-input": None}[plug],
    )
    assert [plug for plug, _ in snap.missing_interfaces(SNAP_ENV)] == ["audio-record"]


def test_missing_interfaces_is_empty_when_all_connected(in_snap) -> None:
    in_snap.setattr(snap, "interface_connected", lambda plug, env=None: True)
    assert snap.missing_interfaces(SNAP_ENV) == []


def test_advice_names_the_instance_not_the_snap_name() -> None:
    """A parallel install is `yazses_beta`; `snap connect yazses:...` misses it."""
    advice = snap.connection_advice(
        snap.REQUIRED_INTERFACES, {"SNAP_INSTANCE_NAME": "yazses_beta", "SNAP": "/x"}
    )
    assert "sudo snap connect yazses_beta:audio-record" in advice
    assert "sudo snap connect yazses_beta:raw-input" in advice


def test_advice_is_empty_when_nothing_is_missing() -> None:
    assert snap.connection_advice([]) == ""


def test_advice_tells_the_user_to_restart() -> None:
    """Connecting an interface does not reattach a running daemon to the mic."""
    advice = snap.connection_advice(snap.REQUIRED_INTERFACES, SNAP_ENV)
    assert "yazses restart" in advice


def test_advice_explains_what_each_interface_buys() -> None:
    advice = snap.connection_advice(snap.REQUIRED_INTERFACES, SNAP_ENV)
    assert "microphone" in advice
    assert "hold-to-talk" in advice


# ------------------------------------------------------------------ doctor


def test_doctor_emits_nothing_outside_a_snap(monkeypatch) -> None:
    from yazses.system import doctor

    monkeypatch.delenv("SNAP_NAME", raising=False)
    monkeypatch.delenv("SNAP", raising=False)
    assert doctor._snap_interface_checks() == []


def test_doctor_fails_loudly_on_a_disconnected_interface(monkeypatch) -> None:
    from yazses.system import doctor

    monkeypatch.setenv("SNAP_NAME", "yazses")
    monkeypatch.setattr(snap, "interface_connected", lambda plug, env=None: False)
    rows = doctor._snap_interface_checks()
    assert {status for _, status, _ in rows} == {"FAIL"}
    assert any("snap connect" in msg for _, _, msg in rows)


def test_doctor_warns_rather_than_fails_when_it_cannot_tell(monkeypatch) -> None:
    """An unrun probe must not report a finding -- it reports that it could not run."""
    from yazses.system import doctor

    monkeypatch.setenv("SNAP_NAME", "yazses")
    monkeypatch.setattr(snap, "interface_connected", lambda plug, env=None: None)
    assert {status for _, status, _ in doctor._snap_interface_checks()} == {"WARN"}


def test_doctor_is_ok_when_connected(monkeypatch) -> None:
    from yazses.system import doctor

    monkeypatch.setenv("SNAP_NAME", "yazses")
    monkeypatch.setattr(snap, "interface_connected", lambda plug, env=None: True)
    assert {status for _, status, _ in doctor._snap_interface_checks()} == {"OK"}
