"""Where implicit refinement meets the daemon, the targeter and the command line (#398).

`test_gaze_refine.py` pins the policy and the store; `test_gaze_refine_runtime.py` pins the
assembly. This file is the last mile: that the running targeter really switches maps, that the
daemon starts refinement only on its own preconditions and says so when it does not, that
shutdown releases it before the camera, and that the user can *see* which kind of map is
active and *undo* a refinement from a command.

Hermetic: fake observer/perception/targeter, a tmp_path data directory, and `CliRunner` with
the platform and config patched the way the neighbouring gaze CLI tests do.
"""
from __future__ import annotations

import dataclasses
import logging
import types
from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

import yazses.cli as cli
from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.gaze.calibrate import CalibrationMap
from yazses.gaze.store import (
    RefinementInfo,
    calibration_path,
    promote_refinement,
    save_calibration,
)
from yazses.gaze.targeter import GazeTargeter
from yazses.platform import get_platform

runner = CliRunner()

IDENT = CalibrationMap(A=np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]))
SHIFT = CalibrationMap(A=np.array([[1.0, 0.0, 600.0], [0.0, 1.0, 0.0]]))


# --------------------------------------------------------------------------- #
# The targeter can switch maps between two holds
# --------------------------------------------------------------------------- #


class OneSample:
    name = "one"

    def estimate_sample(self):
        from yazses.gaze.confidence import GazeSample

        return GazeSample(100.0, 500.0, 0.9)

    def estimate(self):
        return (100.0, 500.0)

    def close(self):
        pass


class Desktop:
    def focused_window(self):
        return "editor"

    def list_windows(self):
        return [("editor", 0, 0, 500, 1000), ("browser", 500, 0, 500, 1000)]

    def activate(self, window):
        pass


def test_a_targeter_routes_with_the_map_it_was_last_given() -> None:
    targeter = GazeTargeter(OneSample(), IDENT, Desktop())
    assert targeter.calibration is IDENT
    assert targeter.retarget(activate=False).target == "editor"   # gaze x=100 lands left
    targeter.set_calibration(SHIFT)
    assert targeter.calibration is SHIFT
    assert targeter.retarget(activate=False).target == "browser"  # x=700 lands right


# --------------------------------------------------------------------------- #
# The daemon
# --------------------------------------------------------------------------- #


class FakeObserver:
    def __init__(self):
        self.starts = self.stops = 0

    def start(self, on_click):
        self.starts += 1

    def stop(self):
        self.stops += 1


class FakeLease:
    def __init__(self):
        self.starts = self.stops = 0

    def start(self):
        self.starts += 1

    def stop(self):
        self.stops += 1

    def latest(self):
        return None


class FakePerception:
    def __init__(self):
        self.lease = FakeLease()

    def consumer(self, name):
        return self.lease


def _daemon(
    *, observer: FakeObserver | None = None, enabled: bool = True, reason: str | None = None
) -> Daemon:
    cfg = Config()
    cfg.gaze_refine.enabled = enabled
    cfg.gaze_refine.min_train_samples = 20
    platform = dataclasses.replace(
        get_platform(),
        click_observer_factory=(None if observer is None else (lambda: observer)),
        click_observer_unavailable_reason=reason,
    )
    daemon = Daemon(config=cfg, platform=platform)
    daemon._gaze_targeter = types.SimpleNamespace(calibration=IDENT, set_calibration=lambda m: None)
    daemon._perception = FakePerception()
    daemon._gaze_on_shared_source = True
    daemon._gaze_calibration_facts = (True, "explicit", None)
    return daemon


def test_a_default_install_builds_no_refinement_and_logs_nothing(caplog) -> None:
    daemon = _daemon(observer=FakeObserver(), enabled=False)
    with caplog.at_level(logging.INFO, logger="yazses.core.daemon"):
        assert daemon._build_gaze_refinement(daemon._config) is None
    assert not [r for r in caplog.records if "gaze calibration" in r.getMessage().lower()]


def test_enabled_but_unable_to_run_says_why_in_the_log(caplog) -> None:
    """The symptomless failure this project keeps paying for: on, and doing nothing."""
    daemon = _daemon(observer=None)  # no click observer, and no platform sentence for why
    with caplog.at_level(logging.WARNING, logger="yazses.core.daemon"):
        assert daemon._build_gaze_refinement(daemon._config) is None
    messages = " ".join(r.getMessage() for r in caplog.records)
    assert "enabled but dormant" in messages and "no click observer" in messages


def test_the_dormant_line_names_the_platforms_own_reason_not_a_missing_backend(caplog) -> None:
    """#607: on Wayland the log must say why this session has no clicks, not "not yet"."""
    daemon = _daemon(observer=None, reason="a native Wayland session exposes no global click stream")
    with caplog.at_level(logging.WARNING, logger="yazses.core.daemon"):
        assert daemon._build_gaze_refinement(daemon._config) is None
    messages = " ".join(r.getMessage() for r in caplog.records)
    assert "no global click stream" in messages
    assert "no click observer yet" not in messages


def test_when_every_precondition_holds_the_daemon_starts_refinement_and_stop_gives_both_back() -> None:
    observer = FakeObserver()
    daemon = _daemon(observer=observer)
    runtime = daemon._build_gaze_refinement(daemon._config)
    assert runtime is not None
    assert (observer.starts, daemon._perception.lease.starts) == (1, 1)

    runtime.stop()
    assert (observer.stops, daemon._perception.lease.stops) == (1, 1)


def test_an_unverified_calibration_keeps_refinement_off_even_with_everything_else_present(caplog) -> None:
    daemon = _daemon(observer=FakeObserver())
    daemon._gaze_calibration_facts = (False, "explicit", None)
    with caplog.at_level(logging.WARNING, logger="yazses.core.daemon"):
        assert daemon._build_gaze_refinement(daemon._config) is None
    assert "could not be verified" in " ".join(r.getMessage() for r in caplog.records)


def test_gaze_on_its_own_camera_keeps_refinement_off() -> None:
    daemon = _daemon(observer=FakeObserver())
    daemon._gaze_on_shared_source = False
    assert daemon._build_gaze_refinement(daemon._config) is None


def test_a_builder_that_raises_costs_a_log_line_never_the_daemon(monkeypatch) -> None:
    import yazses.gaze.refine_runtime as runtime_module

    def boom(*a, **k):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(runtime_module, "build_refinement_runtime", boom)
    daemon = _daemon(observer=FakeObserver())
    assert daemon._build_gaze_refinement(daemon._config) is None


def test_the_daemons_shutdown_stops_refinement_before_it_closes_the_gaze_camera(mocker) -> None:
    order: list[str] = []
    daemon = Daemon(config=Config(), platform=get_platform())
    mocker.patch.object(daemon._platform.lifecycle, "clear_pid")  # not the host's pid file
    daemon._gaze_refinement = types.SimpleNamespace(stop=lambda: order.append("refinement"))
    daemon._gaze_targeter = types.SimpleNamespace(close=lambda: order.append("targeter"))
    daemon._shutdown()
    assert order == ["refinement", "targeter"], (
        "the click hook and its camera lease must be given back before the camera owner closes"
    )


# --------------------------------------------------------------------------- #
# The command line
# --------------------------------------------------------------------------- #


def _platform(tmp_path: Path, **attrs):
    return types.SimpleNamespace(
        paths=types.SimpleNamespace(config_file=tmp_path / "config.toml", data_dir=tmp_path),
        **attrs,
    )


def _status(monkeypatch, tmp_path: Path, *, cfg: Config | None = None, **platform_attrs):
    monkeypatch.setattr(cli, "get_platform", lambda: _platform(tmp_path, **platform_attrs))
    monkeypatch.setattr("yazses.config.load_config", lambda _p: cfg or Config())
    monkeypatch.setattr("yazses.gaze.factory.build_gaze", lambda _cfg: None)
    monkeypatch.setattr("yazses.gaze.desktop.build_desktop", lambda: object())
    return runner.invoke(cli.app, ["gaze", "status"])


def _info() -> RefinementInfo:
    return RefinementInfo(60, 20, 140.0, 12.5)


def test_status_says_an_explicit_map_is_explicit(monkeypatch, tmp_path) -> None:
    save_calibration(IDENT, tmp_path)
    result = _status(monkeypatch, tmp_path)
    assert result.exit_code == 0, result.output
    assert "active map: explicit calibration" in result.output
    assert "gaze rollback" not in result.output, "no rollback is on offer when none exists"
    assert "[gaze_refine] enabled = False" in result.output


def test_status_says_when_the_active_map_was_refined_and_how_it_earned_it(monkeypatch, tmp_path) -> None:
    save_calibration(IDENT, tmp_path)
    promote_refinement(tmp_path, SHIFT, _info())
    result = _status(monkeypatch, tmp_path)
    assert "implicitly refined from clicks" in result.output
    assert "140.0 px → 12.5 px over 60+20 click pairs" in result.output
    assert "`yazses gaze rollback` restores it exactly" in result.output


def _refine_on() -> Config:
    cfg = Config()
    cfg.gaze_refine.enabled = True
    return cfg


def test_status_has_no_click_observer_line_while_refinement_is_off(monkeypatch, tmp_path) -> None:
    save_calibration(IDENT, tmp_path)
    result = _status(monkeypatch, tmp_path)
    assert result.exit_code == 0, result.output
    assert "click observer" not in result.output, "a default install is not told about clicks"


def test_status_says_a_click_observer_is_registered(monkeypatch, tmp_path) -> None:
    save_calibration(IDENT, tmp_path)
    result = _status(monkeypatch, tmp_path, cfg=_refine_on(), click_observer_factory=object)
    assert result.exit_code == 0, result.output
    assert "✓ click observer: registered for this session" in result.output


def test_status_names_why_this_session_has_no_click_observer(monkeypatch, tmp_path) -> None:
    save_calibration(IDENT, tmp_path)
    result = _status(
        monkeypatch, tmp_path, cfg=_refine_on(), click_observer_factory=None,
        click_observer_unavailable_reason="a native Wayland session exposes no global click stream",
    )
    assert result.exit_code == 0, result.output
    assert ("✗ click observer: none -- a native Wayland session exposes no global click stream; "
            "implicit refinement stays dormant") in result.output


def test_status_without_a_platform_reason_falls_back_to_the_generic_sentence(monkeypatch, tmp_path) -> None:
    save_calibration(IDENT, tmp_path)
    result = _status(monkeypatch, tmp_path, cfg=_refine_on())
    assert result.exit_code == 0, result.output
    assert "✗ click observer: none -- this platform has no click observer yet" in result.output


def test_rollback_restores_the_exact_previous_file(monkeypatch, tmp_path) -> None:
    save_calibration(IDENT, tmp_path)
    original = calibration_path(tmp_path).read_bytes()
    promote_refinement(tmp_path, SHIFT, _info())
    monkeypatch.setattr(cli, "get_platform", lambda: _platform(tmp_path))

    result = runner.invoke(cli.app, ["gaze", "rollback"])

    assert result.exit_code == 0, result.output
    assert "Restored the previous calibration" in result.output
    assert "yazses restart" in result.output
    assert calibration_path(tmp_path).read_bytes() == original


def test_rollback_with_nothing_to_roll_back_says_so_and_changes_nothing(monkeypatch, tmp_path) -> None:
    save_calibration(IDENT, tmp_path)
    before = calibration_path(tmp_path).read_bytes()
    monkeypatch.setattr(cli, "get_platform", lambda: _platform(tmp_path))
    result = runner.invoke(cli.app, ["gaze", "rollback"])
    assert result.exit_code == 0
    assert "Nothing to roll back" in result.output
    assert calibration_path(tmp_path).read_bytes() == before


def test_rollback_refuses_an_unreadable_copy_and_exits_nonzero(monkeypatch, tmp_path) -> None:
    from yazses.gaze.store import previous_calibration_path

    save_calibration(IDENT, tmp_path)
    previous_calibration_path(tmp_path).write_text("garbage", encoding="utf-8")
    before = calibration_path(tmp_path).read_bytes()
    monkeypatch.setattr(cli, "get_platform", lambda: _platform(tmp_path))
    result = runner.invoke(cli.app, ["gaze", "rollback"])
    assert result.exit_code == 1
    assert "Could not roll back" in result.output
    assert calibration_path(tmp_path).read_bytes() == before


def test_the_config_section_ships_off_and_its_keys_are_all_read() -> None:
    cfg = Config()
    assert cfg.gaze_refine.enabled is False
    assert cfg.gaze_refine.holdout_every >= 2
    assert pytest.approx(0.5) == cfg.gaze_refine.min_confidence
