"""`yazses gaze calibrate` auto-installs the webcam gaze deps on first run.

The direct calibrate/status entry points must be as turnkey as
`yazses features enable gaze`: when mediapipe/opencv are absent they are
installed into the running environment rather than dead-ending on a manual
`pip install` hint.

**But only once the free questions have been asked.** These fixtures used to build a
bare ``Config()`` -- in which ``[gaze] enabled`` is ``False`` -- and assert that the
installer ran anyway, so the suite required the ~219 MB download on exactly the machine
where calibration was about to refuse. The turnkey intent is unchanged and still tested;
the fixtures now describe a machine where calibrating is actually possible. The ordering
itself is pinned next door in ``test_gaze_calibrate_asks_the_free_questions_first.py``.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

import yazses.cli as cli
from yazses.config import Config, GazeConfig

runner = CliRunner()


def _ready_config() -> Config:
    """A machine where calibration can actually run: the feature is on."""
    import dataclasses

    return dataclasses.replace(Config(), gaze=dataclasses.replace(GazeConfig(), enabled=True))


def _fake_platform(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(paths=SimpleNamespace(config_file=tmp_path / "config.toml",
                                                 data_dir=tmp_path))


def test_calibrate_invokes_dep_install(monkeypatch, tmp_path):
    """calibrate runs the feature-deps installer for gaze before building the backend."""
    calls: list[tuple[str, bool]] = []

    monkeypatch.setattr(cli, "get_platform", lambda: _fake_platform(tmp_path))
    monkeypatch.setattr("yazses.config.load_config", lambda _p: _ready_config())
    monkeypatch.setattr("yazses.gaze.desktop.build_desktop", lambda: object())
    monkeypatch.setattr(cli, "_install_feature_deps",
                        lambda feat, *, skip: calls.append((feat.slug, skip)))
    # Backend stays None so we exit right after the install attempt (no webcam).
    monkeypatch.setattr("yazses.gaze.factory.build_gaze", lambda _cfg: None)

    result = runner.invoke(cli.app, ["gaze", "calibrate"])

    assert calls == [("gaze", False)], result.output
    assert result.exit_code == 1  # backend None → clean bail, not a crash


def test_calibrate_no_install_flag_skips(monkeypatch, tmp_path):
    """--no-install threads through as skip=True (parity with `features enable`)."""
    calls: list[tuple[str, bool]] = []

    monkeypatch.setattr(cli, "get_platform", lambda: _fake_platform(tmp_path))
    monkeypatch.setattr("yazses.config.load_config", lambda _p: _ready_config())
    monkeypatch.setattr("yazses.gaze.desktop.build_desktop", lambda: object())
    monkeypatch.setattr(cli, "_install_feature_deps",
                        lambda feat, *, skip: calls.append((feat.slug, skip)))
    monkeypatch.setattr("yazses.gaze.factory.build_gaze", lambda _cfg: None)

    runner.invoke(cli.app, ["gaze", "calibrate", "--no-install"])

    assert calls == [("gaze", True)]


def test_unavailable_message_drops_l2cs_pip_hint(monkeypatch, tmp_path):
    """The dead-end message points at the turnkey command, not `pip install l2cs`."""
    monkeypatch.setattr(cli, "get_platform", lambda: _fake_platform(tmp_path))
    monkeypatch.setattr("yazses.config.load_config", lambda _p: _ready_config())
    monkeypatch.setattr("yazses.gaze.desktop.build_desktop", lambda: object())
    monkeypatch.setattr(cli, "_install_feature_deps", lambda feat, *, skip: None)
    monkeypatch.setattr("yazses.gaze.factory.build_gaze", lambda _cfg: None)

    result = runner.invoke(cli.app, ["gaze", "calibrate"])

    assert "pip install l2cs" not in result.output
    assert "features enable gaze" in result.output
