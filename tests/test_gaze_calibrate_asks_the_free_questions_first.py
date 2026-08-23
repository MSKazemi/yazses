"""`yazses gaze calibrate` must not download 219 MB before refusing.

Two of the three things that can stop calibration are free to check: `[gaze] enabled`
is a config flag, and the X11/`xdotool` desktop backend is a probe of the running
session. Only the third -- are the webcam dependencies present -- genuinely needs an
install, and it is the only one an install repairs.

They used to be checked in the opposite order. On a default install (`[gaze] enabled`
is `False`) `yazses gaze calibrate` printed *"this downloads up to ~219 MB (12
packages)"*, fetched it, and then said *"Ensure `[gaze] enabled = true`"*. On Wayland it
fetched the same 219 MB to announce that external window focus is forbidden there --
something no download can change.

The project had already settled the principle elsewhere: `system/backends.py` exists so
a factory "never sends the user after an extra that cannot supply that backend".
"""
from __future__ import annotations

import dataclasses
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import yazses.cli as cli
from yazses.config import Config, GazeConfig
from yazses.gaze.calibrate import calibration_blocker

runner = CliRunner()


# ---- the pure decision ---------------------------------------------------------


def test_a_disabled_feature_is_refused_and_names_the_command_that_fixes_it():
    blocked = calibration_blocker(enabled=False, desktop_ok=True)
    assert blocked is not None
    assert "features enable gaze --force" in blocked


def test_wayland_is_refused_and_says_installing_cannot_help():
    """The strongest case: on Wayland the download can never become useful."""
    blocked = calibration_blocker(enabled=True, desktop_ok=False)
    assert blocked is not None
    assert "X11" in blocked
    assert "cannot make this work" in blocked


def test_a_machine_that_can_calibrate_is_not_blocked():
    assert calibration_blocker(enabled=True, desktop_ok=True) is None


def test_the_dependency_case_is_deliberately_not_decided_here():
    """It is the one question an install answers, so it stays after the install."""
    assert calibration_blocker(enabled=True, desktop_ok=True) is None


# ---- the command a user actually types -----------------------------------------


def _platform(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        paths=SimpleNamespace(config_file=tmp_path / "config.toml", data_dir=tmp_path)
    )


def _config(*, enabled: bool) -> Config:
    return dataclasses.replace(
        Config(), gaze=dataclasses.replace(GazeConfig(), enabled=enabled)
    )


def _run(monkeypatch, tmp_path, *, enabled: bool, x11: bool):
    """Invoke `gaze calibrate`, recording whether the installer was reached."""
    installs: list[str] = []
    monkeypatch.setattr(cli, "get_platform", lambda: _platform(tmp_path))
    monkeypatch.setattr("yazses.config.load_config", lambda _p: _config(enabled=enabled))
    monkeypatch.setattr(
        "yazses.gaze.desktop.build_desktop", lambda: (object() if x11 else None)
    )
    monkeypatch.setattr(
        cli, "_install_feature_deps", lambda feat, *, skip: installs.append(feat.slug)
    )
    # Never reached in the blocked cases; a clean bail in the unblocked one.
    monkeypatch.setattr("yazses.gaze.factory.build_gaze", lambda _cfg: None)
    return runner.invoke(cli.app, ["gaze", "calibrate"]), installs


@pytest.mark.parametrize(
    ("enabled", "x11"),
    [(False, True), (True, False), (False, False)],
)
def test_nothing_is_downloaded_when_calibration_cannot_work(monkeypatch, tmp_path, enabled, x11):
    result, installs = _run(monkeypatch, tmp_path, enabled=enabled, x11=x11)
    assert installs == [], result.output
    assert result.exit_code == 1


def test_the_refusal_does_not_quote_a_download_size(monkeypatch, tmp_path):
    """The size note is printed by the installer, so reaching it is the failure."""
    result, _ = _run(monkeypatch, tmp_path, enabled=False, x11=True)
    assert "MB" not in result.output, result.output
    assert "downloads up to" not in result.output


def test_a_machine_that_can_calibrate_still_installs(monkeypatch, tmp_path):
    """The control: the reorder must not have turned the turnkey install off."""
    result, installs = _run(monkeypatch, tmp_path, enabled=True, x11=True)
    assert installs == ["gaze"], result.output


def test_status_does_not_point_a_disabled_machine_at_calibrate(monkeypatch, tmp_path):
    """`gaze status` used to offer `gaze calibrate` as the alternative — which refuses."""
    monkeypatch.setattr(cli, "get_platform", lambda: _platform(tmp_path))
    monkeypatch.setattr("yazses.config.load_config", lambda _p: _config(enabled=False))
    monkeypatch.setattr("yazses.gaze.factory.build_gaze", lambda _cfg: None)
    monkeypatch.setattr("yazses.gaze.desktop.build_desktop", lambda: object())
    monkeypatch.setattr("yazses.gaze.store.load_calibration", lambda _d: None)

    result = runner.invoke(cli.app, ["gaze", "status"])

    assert result.exit_code == 0, result.output
    tail = result.output.split("Next:")[-1]
    assert "features enable gaze --force" in tail
    assert "or run `yazses gaze calibrate`" not in tail
