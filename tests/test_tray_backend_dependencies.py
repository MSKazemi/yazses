"""The tray is launched, and judged, by what its own backend imports.

Every "can the tray run?" check asked for PySide6. The Windows tray is pystray + Pillow,
and the macOS one is rumps, all base dependencies on their platforms. So on a pip, pipx
or uv install on Windows (pystray yes, Qt no):
- the daemon skipped the tray, and with it the only thing that restarts a crashed
  daemon there, so a crash meant no dictation until the next sign-in;
- the user was offered a 268 MB PySide6 download for a tray that never uses it.
"""

from __future__ import annotations

import types

import pytest

from yazses.system import dormant
from yazses.tray import launch


class _PystrayTray:
    RUNTIME_MODULES = ("pystray", "PIL")


def _platform(tray_factory):
    return types.SimpleNamespace(tray_factory=tray_factory)


# ---- what each backend declares -------------------------------------------------


def test_the_windows_tray_declares_pystray_and_pillow_not_qt():
    from yazses.platform.windows.tray import WindowsTray

    assert launch.tray_runtime_modules(_platform(WindowsTray)) == ("pystray", "PIL")


def test_the_macos_tray_declares_rumps_not_qt():
    from yazses.platform.macos.tray import MacosTray

    assert launch.tray_runtime_modules(_platform(MacosTray)) == ("rumps",)


def test_a_backend_built_by_a_factory_function_is_the_qt_tray():
    def _make_tray():  # how Linux and the BSDs register theirs
        raise AssertionError("must not be called just to ask what it needs")

    assert launch.tray_runtime_modules(_platform(_make_tray)) == ("PySide6",)


def test_a_platform_without_a_tray_keeps_the_old_answer():
    assert launch.tray_runtime_modules(_platform(None)) == ("PySide6",)


# ---- the launch decision ---------------------------------------------------------


def test_a_tray_whose_modules_import_is_available():
    class _Importable:
        RUNTIME_MODULES = ("json", "pathlib")

    assert launch.tray_dependency_available(_platform(_Importable))
    assert launch.missing_tray_modules(_platform(_Importable)) == []


def test_a_tray_whose_module_is_absent_is_not_and_says_which():
    class _Absent:
        RUNTIME_MODULES = ("json", "no_such_tray_module_xyz")

    assert not launch.tray_dependency_available(_platform(_Absent))
    assert launch.missing_tray_modules(_platform(_Absent)) == ["no_such_tray_module_xyz"]


def _daemon_with_tray(mocker, tray_cls):
    from dataclasses import replace

    from yazses.config import Config
    from yazses.core.daemon import Daemon
    from yazses.platform import get_platform

    d = Daemon(config=Config(), platform=replace(get_platform(), tray_factory=tray_cls))
    mocker.patch("yazses.tray.launch.should_launch_tray", return_value=True)
    popen = mocker.patch("yazses.core.daemon.subprocess.Popen")
    popen.return_value.pid = 4242
    mocker.patch.object(d, "_start_tray_supervisor")
    return d, popen


def test_the_daemon_launches_a_tray_that_needs_no_qt_where_qt_is_absent(mocker):
    """The Windows pip/pipx case: the tray's own modules import, PySide6 does not."""
    class _NoQtTray:
        RUNTIME_MODULES = ("json",)

    real_find_spec = __import__("importlib.util").util.find_spec
    mocker.patch(
        "importlib.util.find_spec",
        side_effect=lambda name, *a: None if name == "PySide6" else real_find_spec(name, *a),
    )
    d, popen = _daemon_with_tray(mocker, _NoQtTray)
    d._maybe_launch_tray()
    popen.assert_called_once()
    d._start_tray_supervisor.assert_called_once()  # crash recovery goes with it


def test_the_daemon_names_the_missing_module_when_it_cannot(mocker, caplog):
    class _Absent:
        RUNTIME_MODULES = ("no_such_tray_module_xyz",)

    d, popen = _daemon_with_tray(mocker, _Absent)
    with caplog.at_level("INFO"):
        d._maybe_launch_tray()
    popen.assert_not_called()
    assert "no_such_tray_module_xyz is not installed" in caplog.text


# ---- the "switched on but not installed" warning ---------------------------------


def _tray_row():
    # The registry's row, as `feature_status` builds it: PySide6 on every platform.
    return types.SimpleNamespace(
        slug="tray", name="System-tray icon", on=True, wired=True, tier="core",
        check_modules=("PySide6",), pip_packages=("PySide6>=6.11.1",),
    )


def _qt_absent(modules):
    return [m for m in modules if m == "PySide6"]


@pytest.mark.parametrize("platform_modules", [("pystray", "PIL"), ("rumps",)])
def test_a_tray_that_needs_no_qt_is_not_reported_dormant_without_qt(platform_modules):
    found = dormant.dormant_features(
        None, features=[_tray_row()], missing=_qt_absent, blocked=lambda p: None,
        graphical=lambda: True, tray_modules=lambda: platform_modules,
    )
    assert found == [], "Windows/macOS users were told to fetch 268 MB of Qt"


def test_the_qt_tray_without_qt_is_still_reported():
    (only,) = dormant.dormant_features(
        None, features=[_tray_row()], missing=_qt_absent, blocked=lambda p: None,
        graphical=lambda: True, tray_modules=lambda: ("PySide6",),
    )
    assert only.slug == "tray"


def test_a_tray_whose_own_modules_are_missing_is_reported():
    (only,) = dormant.dormant_features(
        None, features=[_tray_row()], missing=lambda mods: list(mods),
        blocked=lambda p: None, graphical=lambda: True,
        tray_modules=lambda: ("pystray", "PIL"),
    )
    assert only.missing == ("pystray", "PIL")
