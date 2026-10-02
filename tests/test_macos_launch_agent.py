"""The macOS login agent must launch the daemon the way this install can be launched.

It used to be ``[sys.executable, "-m", "yazses.main"]``. In the .app bundle
``sys.executable`` is the bundle, which has no ``-m``: it printed "No such option:
-m" and exited 2, so the launchd agent that ``doctor`` called "loaded" never started
a daemon. The plist is rendered by a pure function, so none of this needs a Mac.
"""

from __future__ import annotations

import plistlib
from pathlib import Path

from yazses.platform.macos.lifecycle import render_launch_agent
from yazses.system.relaunch import Mode, command_for

_APP = Path("/Applications/YazSes.app/Contents/MacOS/YazSes")


def _args(argv: list[str]) -> list[str]:
    xml = render_launch_agent(argv, stdout=Path("/tmp/o.log"), stderr=Path("/tmp/e.log"))
    return plistlib.loads(xml.encode("utf-8"))["ProgramArguments"]


def test_frozen_bundle_is_started_with_the_daemon_flag_not_dash_m() -> None:
    argv = command_for(
        Mode.DAEMON, frozen=True, executable=_APP, windows=False, exists=lambda _p: False
    )
    assert _args(argv) == [str(_APP), "--daemon"]
    assert "-m" not in _args(argv)


def test_pip_install_still_runs_the_module() -> None:
    argv = command_for(
        Mode.DAEMON,
        frozen=False,
        executable=Path("/opt/py/bin/python"),
        windows=False,
        which=lambda _name: None,
        exists=lambda _p: False,
    )
    assert _args(argv) == ["/opt/py/bin/python", "-m", "yazses.main"]


def test_a_path_with_xml_metacharacters_survives_the_round_trip() -> None:
    nasty = "/Users/a&b/<x>/YazSes"
    assert _args([nasty, "--daemon"]) == [nasty, "--daemon"]


def test_plist_keeps_its_keys() -> None:
    xml = render_launch_agent([str(_APP), "--daemon"], stdout=Path("/o"), stderr=Path("/e"))
    data = plistlib.loads(xml.encode("utf-8"))
    assert data["Label"] == "com.yazses.daemon"
    assert data["RunAtLoad"] is True
    assert data["StandardOutPath"] == "/o"
    assert data["StandardErrorPath"] == "/e"
